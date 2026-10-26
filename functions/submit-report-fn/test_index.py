"""Tests for SubmitReport. Run with: python -m pytest"""
import importlib.util
import json
import os
import pathlib
import sys
import time
from typing import Any

import boto3
import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
_spec = importlib.util.spec_from_file_location(f"{__name__}_index", pathlib.Path(__file__).with_name("index.py"))
assert _spec and _spec.loader
index = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = index  # dataclasses look the module up while it loads
_spec.loader.exec_module(index)

ADMIN = {"x-admin-key": "correct-horse-battery"}
VALID = {"area": "Downtown", "category": "illegal-dumping", "description": "Mattress left on the pavement"}


@pytest.fixture(autouse=True)
def fake_aws(reports_table: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ADMIN_KEY", "correct-horse-battery")
    monkeypatch.setattr(index, "dynamodb", boto3.resource("dynamodb"))
    return reports_table


def call(route: str, body: Any = None, headers: dict[str, str] | None = None, report_id: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"routeKey": route, "headers": headers or {}, "isBase64Encoded": False}
    if body is not None:
        event["body"] = body if isinstance(body, str) else json.dumps(body)
    if report_id:
        event["pathParameters"] = {"reportId": report_id}
    return index.handler(event, None)


def create() -> dict[str, Any]:
    res = call("POST /reports", VALID)
    assert res["statusCode"] == 201
    return json.loads(res["body"])


def set_expiry(table: Any, report_id: str, value: int) -> None:
    key = {"pk": f"REPORT#{report_id}", "sk": "REPORT"}
    table.update_item(Key=key, UpdateExpression="SET expiresAt = :e", ExpressionAttributeValues={":e": value})


def stored(table: Any, report_id: str) -> dict[str, Any]:
    return table.get_item(Key={"pk": f"REPORT#{report_id}", "sk": "REPORT"})["Item"]


# ---- POST /reports
def test_create_saves_a_clean_report(fake_aws: Any) -> None:
    report = create()
    assert report["status"] == "open"
    assert report["area"] == "downtown"  # lower-cased
    assert "pk" not in report and "sk" not in report
    item = stored(fake_aws, report["reportId"])
    assert abs(int(item["expiresAt"]) - (time.time() + 90 * 86400)) < 60  # TTL is 90 days out


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"area": None}, "'area'"),
        ({"category": ""}, "'category'"),
        ({"description": "   "}, "'description'"),
        ({"description": 123}, "'description'"),
        ({"description": "x" * 501}, "500"),
        ({"category": "graffiti"}, "one of"),
    ],
)
def test_invalid_reports_are_rejected(change: dict[str, Any], fragment: str, fake_aws: Any) -> None:
    body = {**VALID, **change}
    if change.get("area", "x") is None:
        del body["area"]
    res = call("POST /reports", body)
    assert res["statusCode"] == 400
    assert fragment in json.loads(res["body"])["message"]
    assert fake_aws.scan()["Count"] == 0  # nothing junk was saved


def test_500_characters_is_allowed() -> None:
    assert call("POST /reports", {**VALID, "description": "x" * 500})["statusCode"] == 201


@pytest.mark.parametrize("body", ["not json", "[1, 2]", None])
def test_bad_bodies_are_rejected(body: Any) -> None:
    assert call("POST /reports", body)["statusCode"] == 400


# ---- PATCH /reports/{reportId}/status
PATCH = "PATCH /reports/{reportId}/status"


@pytest.mark.parametrize("headers", [{}, {"x-admin-key": "wrong"}])
def test_patch_needs_the_admin_key(headers: dict[str, str], fake_aws: Any) -> None:
    report = create()
    res = call(PATCH, {"status": "resolved"}, headers, report["reportId"])
    assert res["statusCode"] == 401
    assert stored(fake_aws, report["reportId"])["status"] == "open"


def test_patch_fails_closed_when_no_admin_key_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_KEY", "")
    assert call(PATCH, {"status": "resolved"}, {"x-admin-key": ""}, "abc")["statusCode"] == 401


def test_resolving_restarts_the_90_day_clock(fake_aws: Any) -> None:
    report = create()
    set_expiry(fake_aws, report["reportId"], 1000)
    res = call(PATCH, {"status": "resolved"}, ADMIN, report["reportId"])
    assert res["statusCode"] == 200
    item = stored(fake_aws, report["reportId"])
    assert item["status"] == "resolved"
    assert abs(int(item["expiresAt"]) - (time.time() + 90 * 86400)) < 60


def test_in_progress_leaves_the_expiry_alone(fake_aws: Any) -> None:
    report = create()
    set_expiry(fake_aws, report["reportId"], 1000)
    assert call(PATCH, {"status": "in-progress"}, ADMIN, report["reportId"])["statusCode"] == 200
    item = stored(fake_aws, report["reportId"])
    assert item["status"] == "in-progress" and int(item["expiresAt"]) == 1000


@pytest.mark.parametrize("body", [{"status": "open"}, {"status": "banana"}, {}, "nope"])
def test_patch_rejects_bad_statuses(body: Any) -> None:
    assert call(PATCH, body, ADMIN, "abc")["statusCode"] == 400


def test_patch_unknown_report_is_404_and_creates_nothing(fake_aws: Any) -> None:
    assert call(PATCH, {"status": "resolved"}, ADMIN, "does-not-exist")["statusCode"] == 404
    assert fake_aws.scan()["Count"] == 0


def test_unknown_route() -> None:
    assert call("DELETE /reports/1")["statusCode"] == 404

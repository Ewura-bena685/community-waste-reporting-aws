"""Tests for GetReports. Run with: python -m pytest"""
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

FUTURE = int(time.time()) + 86400


@pytest.fixture(autouse=True)
def fake_aws(reports_table: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(index, "dynamodb", boto3.resource("dynamodb"))
    for rid, area, status, created in [
        ("r1", "downtown", "open", "2026-01-01T10:00:00+00:00"),
        ("r2", "downtown", "resolved", "2026-01-02T10:00:00+00:00"),
        ("r3", "downtown", "open", "2026-01-03T10:00:00+00:00"),
        ("r4", "uptown", "open", "2026-01-04T10:00:00+00:00"),
    ]:
        reports_table.put_item(
            Item={"pk": f"REPORT#{rid}", "sk": "REPORT", "reportId": rid, "area": area, "status": status, "createdAt": created, "expiresAt": FUTURE}
        )
    # Newest of all, but already expired: DynamoDB may keep such an item for a while before deleting it.
    expired = {"pk": "REPORT#old", "sk": "REPORT", "reportId": "old", "area": "downtown", "status": "open"}
    reports_table.put_item(Item={**expired, "createdAt": "2026-01-05T10:00:00+00:00", "expiresAt": 1000})
    return reports_table


def get(route: str, query: dict[str, str] | None = None, report_id: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"routeKey": route, "queryStringParameters": query}
    if report_id:
        event["pathParameters"] = {"reportId": report_id}
    return index.handler(event, None)


def ids(res: dict[str, Any]) -> list[str]:
    return [i["reportId"] for i in json.loads(res["body"])["items"]]


def test_list_by_area_is_newest_first_and_hides_expired_items() -> None:
    res = get("GET /reports", {"area": "downtown"})
    assert res["statusCode"] == 200
    assert ids(res) == ["r3", "r2", "r1"]  # "old" is expired so it is hidden


def test_area_is_case_insensitive() -> None:
    assert ids(get("GET /reports", {"area": " Uptown "})) == ["r4"]


def test_list_by_area_and_status() -> None:
    assert ids(get("GET /reports", {"area": "downtown", "status": "resolved"})) == ["r2"]


def test_list_defaults_to_open_reports() -> None:
    assert ids(get("GET /reports")) == ["r4", "r3", "r1"]


def test_list_by_status_only() -> None:
    assert ids(get("GET /reports", {"status": "resolved"})) == ["r2"]


def test_limit_is_applied() -> None:
    assert ids(get("GET /reports", {"area": "downtown", "limit": "1"})) == ["r3"]


@pytest.mark.parametrize("query", [{"status": "banana"}, {"limit": "lots"}])
def test_bad_query_parameters_are_400(query: dict[str, str]) -> None:
    assert get("GET /reports", query)["statusCode"] == 400


def test_responses_hide_internal_keys() -> None:
    item = json.loads(get("GET /reports", {"area": "uptown"})["body"])["items"][0]
    assert "pk" not in item and "sk" not in item


def test_get_one_report() -> None:
    res = get("GET /reports/{reportId}", report_id="r1")
    assert res["statusCode"] == 200
    assert json.loads(res["body"])["area"] == "downtown"


@pytest.mark.parametrize("rid", ["missing", "old"])
def test_missing_or_expired_report_is_404(rid: str) -> None:
    assert get("GET /reports/{reportId}", report_id=rid)["statusCode"] == 404


def test_unknown_route() -> None:
    assert get("POST /reports")["statusCode"] == 404

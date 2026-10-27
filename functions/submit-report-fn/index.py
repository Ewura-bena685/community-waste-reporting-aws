"""SubmitReport function: the write side of the API.

  POST  /reports                      validate and save a new waste report (public)
  PATCH /reports/{reportId}/status    mark a report in-progress or resolved (admin only)

Environment (set by the template):
  REPORTS_TABLE_TABLE_NAME  name of the DynamoDB table
  ADMIN_KEY                 secret expected in the x-admin-key header for PATCH
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Created once per container and reused across invocations (faster, and less compute = less energy).
dynamodb = boto3.resource("dynamodb")

MAX_LENGTH = 500
CATEGORIES = (
    "illegal-dumping",
    "overflowing-bin",
    "missed-collection",
    "littering",
    "recycling-contamination",
    "hazardous-waste",
    "e-waste",
    "other",
)
STATUSES = ("in-progress", "resolved")  # statuses an admin may set ("open" is only the starting value)
RETENTION_DAYS = 90


def table() -> Any:
    return dynamodb.Table(os.environ["REPORTS_TABLE_TABLE_NAME"])


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):  # DynamoDB hands numbers back as Decimal
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Not JSON serialisable: {type(value).__name__}")


def respond(status: int, body: Any = None) -> dict[str, Any]:
    payload = "" if body is None else json.dumps(body, separators=(",", ":"), default=_json_default)
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": payload}


def log(msg: str, **fields: Any) -> None:
    print(json.dumps({"msg": msg, **fields}, default=str))


def expiry(now: datetime) -> int:
    """TTL value: epoch seconds, RETENTION_DAYS from now. DynamoDB deletes the item after this time."""
    return int((now + timedelta(days=RETENTION_DAYS)).timestamp())


def public(item: dict[str, Any]) -> dict[str, Any]:
    """Hide the internal key attributes from API responses."""
    return {k: v for k, v in item.items() if k not in ("pk", "sk")}


def parse_body(event: dict[str, Any]) -> Any:
    text = event.get("body")
    if not text:
        return None
    if event.get("isBase64Encoded"):
        text = base64.b64decode(text).decode("utf-8")
    return json.loads(text)  # raises ValueError if the body is not valid JSON


def validate_report(body: Any) -> tuple[dict[str, str], str | None]:
    """Returns (clean fields, None) when valid, or ({}, error message) when not."""
    if not isinstance(body, dict):
        return {}, "The request body must be a JSON object."
    clean: dict[str, str] = {}
    for field in ("area", "category", "description"):
        value = body.get(field)
        if not isinstance(value, str) or not value.strip():
            return {}, f"'{field}' is required and must be a non-empty string."
        value = value.strip()
        if len(value) > MAX_LENGTH:
            return {}, f"'{field}' must be {MAX_LENGTH} characters or fewer."
        clean[field] = value
    # Lower-case area and category so "Downtown" and "downtown" land in the same index partition.
    clean["area"] = clean["area"].lower()
    clean["category"] = clean["category"].lower()
    if clean["category"] not in CATEGORIES:
        return {}, f"'category' must be one of: {', '.join(CATEGORIES)}."
    return clean, None


def create_report(body: Any) -> dict[str, Any]:
    clean, error = validate_report(body)
    if error:
        return respond(400, {"message": error})
    now = datetime.now(UTC)
    report_id = str(uuid.uuid4())
    item: dict[str, Any] = {
        "pk": f"REPORT#{report_id}",
        "sk": "REPORT",
        "reportId": report_id,
        **clean,
        "status": "open",
        "createdAt": now.isoformat(),
        "expiresAt": expiry(now),
    }
    table().put_item(Item=item)
    return respond(201, public(item))


def is_admin(headers: dict[str, str]) -> bool:
    expected = os.environ.get("ADMIN_KEY", "")
    supplied = headers.get("x-admin-key", "")  # API Gateway lower-cases header names
    # compare_digest takes the same time however many characters match, which blocks timing attacks.
    return bool(expected) and hmac.compare_digest(supplied.encode(), expected.encode())


def update_status(event: dict[str, Any], body: Any) -> dict[str, Any]:
    if not is_admin(event.get("headers") or {}):
        return respond(401, {"message": "Missing or invalid admin key."})
    status = body.get("status") if isinstance(body, dict) else None
    if status not in STATUSES:
        return respond(400, {"message": f"'status' must be one of: {', '.join(STATUSES)}."})
    report_id = event["pathParameters"]["reportId"]
    now = datetime.now(UTC)
    # "status" is a DynamoDB reserved word, so we refer to it through the placeholder #s.
    expression = "SET #s = :s, updatedAt = :u"
    values: dict[str, Any] = {":s": status, ":u": now.isoformat()}
    if status == "resolved":
        expression += ", expiresAt = :e"  # restart the 90-day clock from the day it was resolved
        values[":e"] = expiry(now)
    try:
        result = table().update_item(
            Key={"pk": f"REPORT#{report_id}", "sk": "REPORT"},
            UpdateExpression=expression,
            ConditionExpression="attribute_exists(pk)",  # without this, UpdateItem would create a new item
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return respond(404, {"message": "Report not found."})
        raise
    return respond(200, public(result["Attributes"]))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    route = event.get("routeKey", "")  # e.g. "POST /reports", filled in by API Gateway
    try:
        body = parse_body(event)
    except ValueError:  # also covers bad base64 and bad UTF-8
        return respond(400, {"message": "The request body must be valid JSON."})
    try:
        if route == "POST /reports":
            return create_report(body)
        if route == "PATCH /reports/{reportId}/status":
            return update_status(event, body)
        return respond(404, {"message": f"No route for {route}"})
    except Exception as err:  # never leak internals to the caller
        log("Request failed", route=route, error=str(err))
        return respond(500, {"message": "Something went wrong."})

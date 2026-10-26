"""GetReports function: the read side of the API. It can only read, never change data.

  GET /reports?area=downtown&status=open&limit=50   newest-first list (by area, or by status)
  GET /reports/{reportId}                           one report

Environment (set by the template):
  REPORTS_TABLE_TABLE_NAME  name of the DynamoDB table
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any

import boto3

dynamodb = boto3.resource("dynamodb")

STATUSES = ("open", "in-progress", "resolved")
DEFAULT_LIMIT, MAX_LIMIT = 50, 100


def table() -> Any:
    return dynamodb.Table(os.environ["REPORTS_TABLE_TABLE_NAME"])


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Not JSON serialisable: {type(value).__name__}")


def respond(status: int, body: Any = None) -> dict[str, Any]:
    payload = "" if body is None else json.dumps(body, separators=(",", ":"), default=_json_default)
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": payload}


def log(msg: str, **fields: Any) -> None:
    print(json.dumps({"msg": msg, **fields}, default=str))


def public(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in ("pk", "sk")}


def is_live(item: dict[str, Any]) -> bool:
    """DynamoDB can take up to a few days to delete expired items, so we hide them ourselves."""
    expires = item.get("expiresAt")
    return expires is None or int(expires) > time.time()


def list_reports(query: dict[str, str]) -> dict[str, Any]:
    area = (query.get("area") or "").strip().lower()
    status = (query.get("status") or "").strip().lower()
    if status and status not in STATUSES:
        return respond(400, {"message": f"'status' must be one of: {', '.join(STATUSES)}."})
    try:
        limit = int(query.get("limit") or DEFAULT_LIMIT)
    except ValueError:
        return respond(400, {"message": "'limit' must be a whole number."})
    limit = max(1, min(limit, MAX_LIMIT))

    # DynamoDB rejects placeholders that the expression never uses, so only add the ones we need.
    names: dict[str, str] = {}
    values: dict[str, Any] = {}
    params: dict[str, Any] = {"ScanIndexForward": False, "Limit": limit}  # False = newest first
    if area:
        params.update(IndexName="AreaIndex", KeyConditionExpression="#a = :a")
        names["#a"] = "area"
        values[":a"] = area
        if status:  # optional extra filter, applied by DynamoDB after it reads each page
            params["FilterExpression"] = "#s = :s"
            names["#s"] = "status"
            values[":s"] = status
    else:
        params.update(IndexName="StatusIndex", KeyConditionExpression="#s = :s")
        names["#s"] = "status"  # "status" is a DynamoDB reserved word, hence the placeholder
        values[":s"] = status or "open"
    params["ExpressionAttributeNames"] = names
    params["ExpressionAttributeValues"] = values
    # DynamoDB applies Limit *before* filtering, and we also hide expired items ourselves, so one page can
    # come back short. Keep reading pages until we have `limit` live items or run out of data.
    items: list[dict[str, Any]] = []
    while len(items) < limit:
        page = table().query(**params)
        items += [public(i) for i in page.get("Items", []) if is_live(i)]
        if "LastEvaluatedKey" not in page:
            break
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    items = items[:limit]
    return respond(200, {"items": items, "count": len(items)})


def get_report(report_id: str) -> dict[str, Any]:
    item = table().get_item(Key={"pk": f"REPORT#{report_id}", "sk": "REPORT"}).get("Item")
    if not item or not is_live(item):
        return respond(404, {"message": "Report not found."})
    return respond(200, public(item))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    route = event.get("routeKey", "")
    try:
        if route == "GET /reports":
            return list_reports(event.get("queryStringParameters") or {})
        if route == "GET /reports/{reportId}":
            return get_report(event["pathParameters"]["reportId"])
        return respond(404, {"message": f"No route for {route}"})
    except Exception as err:
        log("Request failed", route=route, error=str(err))
        return respond(500, {"message": "Something went wrong."})

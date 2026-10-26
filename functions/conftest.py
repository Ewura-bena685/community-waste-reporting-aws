"""Shared test setup: a fake AWS (moto) with a DynamoDB table shaped exactly like the one in template.yaml."""
import os
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def reports_table(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("REPORTS_TABLE_TABLE_NAME", "reports-test")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    with mock_aws():
        db = boto3.resource("dynamodb")
        db.create_table(
            TableName="reports-test",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("pk", "sk", "area", "status", "createdAt")],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": name,
                    "KeySchema": [{"AttributeName": key, "KeyType": "HASH"}, {"AttributeName": "createdAt", "KeyType": "RANGE"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for name, key in (("AreaIndex", "area"), ("StatusIndex", "status"))
            ],
        )
        yield db.Table("reports-test")

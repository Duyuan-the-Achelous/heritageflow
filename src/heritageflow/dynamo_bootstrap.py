from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

from .config import load_settings
from .dynamo_service import DynamoReservationService


def ensure_table(resource: Any, client: Any, table_name: str) -> None:
    try:
        client.describe_table(TableName=table_name)
        return
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise

    table = resource.create_table(
        TableName=table_name,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    table.wait_until_exists()


def wait_for_dynamodb(client: Any, attempts: int = 30, delay_seconds: float = 1.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            client.list_tables(Limit=1)
            return
        except (EndpointConnectionError, ClientError):
            if attempt == attempts:
                raise RuntimeError("DynamoDB Local did not become ready")
            time.sleep(delay_seconds)


def main() -> None:
    settings = load_settings()
    if settings.storage_backend != "dynamodb" or not settings.dynamodb_endpoint_url:
        raise RuntimeError("local bootstrap requires the DynamoDB backend and endpoint URL")

    resource = boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=settings.dynamodb_endpoint_url,
    )
    client = boto3.client(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=settings.dynamodb_endpoint_url,
    )
    wait_for_dynamodb(client)
    ensure_table(resource, client, settings.dynamodb_table)
    DynamoReservationService(
        table_name=settings.dynamodb_table,
        visitor_hash_key=settings.visitor_hash_key,
        region_name=settings.aws_region,
        endpoint_url=settings.dynamodb_endpoint_url,
        resource=resource,
        client=client,
    ).seed_demo_data()
    print(f"DynamoDB Local table {settings.dynamodb_table!r} is ready and seeded")


if __name__ == "__main__":
    main()

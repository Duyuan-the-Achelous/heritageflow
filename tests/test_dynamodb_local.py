from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import boto3
import pytest
from fastapi.testclient import TestClient

from heritageflow.config import Settings
from heritageflow.dynamo_bootstrap import ensure_table
from heritageflow.dynamo_service import DynamoReservationService
from heritageflow.main import create_app


pytestmark = pytest.mark.integration


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_complete_api_journey_survives_app_restart(monkeypatch: pytest.MonkeyPatch):
    endpoint = os.getenv("HERITAGEFLOW_INTEGRATION_DYNAMODB_URL")
    if not endpoint:
        pytest.skip("DynamoDB Local integration endpoint is not configured")

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "local")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "local")
    table_name = f"heritageflow-integration-{uuid4().hex}"
    resource = boto3.resource("dynamodb", region_name="eu-west-1", endpoint_url=endpoint)
    client = boto3.client("dynamodb", region_name="eu-west-1", endpoint_url=endpoint)
    ensure_table(resource, client, table_name)
    service = DynamoReservationService(
        table_name=table_name,
        visitor_hash_key="integration-test-key",
        region_name="eu-west-1",
        endpoint_url=endpoint,
        resource=resource,
        client=client,
    )
    service.seed_demo_data()
    settings = Settings(
        environment="development",
        database_path=Path("unused.db"),
        visitor_hash_key="integration-test-key",
        api_keys={},
        storage_backend="dynamodb",
        dynamodb_table=table_name,
        aws_region="eu-west-1",
        dynamodb_endpoint_url=endpoint,
    )

    try:
        with TestClient(create_app(settings)) as first_app:
            slots = first_app.get(
                "/v1/slots",
                params={"attraction_id": "guanlin-main"},
                headers=auth("demo:guanlin:visitor"),
            ).json()
            response = first_app.post(
                "/v1/reservations",
                headers={
                    **auth("demo:guanlin:visitor"),
                    "Idempotency-Key": "integration-key-001",
                },
                json={
                    "attraction_id": "guanlin-main",
                    "slot_id": slots[0]["id"],
                    "visitor_reference": "integration-visitor",
                    "quantity": 1,
                },
            )
            assert response.status_code == 201
            reservation = response.json()

            duplicate = first_app.post(
                "/v1/reservations",
                headers={
                    **auth("demo:guanlin:visitor"),
                    "Idempotency-Key": "integration-key-001",
                },
                json={
                    "attraction_id": "guanlin-main",
                    "slot_id": slots[0]["id"],
                    "visitor_reference": "integration-visitor",
                    "quantity": 1,
                },
            )
            assert duplicate.status_code == 200
            assert duplicate.json()["id"] == reservation["id"]

            foreign = first_app.get(
                f"/v1/reservations/{reservation['id']}",
                headers=auth("demo:tomb-museum:visitor"),
            )
            assert foreign.status_code == 404

        with TestClient(create_app(settings)) as restarted_app:
            persisted = restarted_app.get(
                f"/v1/reservations/{reservation['id']}",
                headers=auth("demo:guanlin:visitor"),
            )
            assert persisted.status_code == 200
            validated = restarted_app.post(
                "/v1/validations",
                headers=auth("demo:guanlin:validator"),
                json={"validation_code": reservation["validation_code"]},
            )
            assert validated.status_code == 200
            second_validation = restarted_app.post(
                "/v1/validations",
                headers=auth("demo:guanlin:validator"),
                json={"validation_code": reservation["validation_code"]},
            )
            assert second_validation.status_code == 409
    finally:
        client.delete_table(TableName=table_name)

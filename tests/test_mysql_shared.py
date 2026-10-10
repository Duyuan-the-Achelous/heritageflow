from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest


pytestmark = pytest.mark.integration


def auth(role: str = "visitor") -> dict[str, str]:
    return {"Authorization": f"Bearer demo:guanlin:{role}"}


def test_two_api_instances_share_capacity_and_constraints():
    api_a = os.getenv("HERITAGEFLOW_INTEGRATION_MYSQL_API_A")
    api_b = os.getenv("HERITAGEFLOW_INTEGRATION_MYSQL_API_B")
    if not api_a or not api_b:
        pytest.skip("MySQL API integration endpoints are not configured")

    with httpx.Client(timeout=10) as client:
        slots = client.get(
            f"{api_a}/v1/slots",
            params={"attraction_id": "guanlin-main"},
            headers=auth(),
        ).json()
        slot = slots[0]
        suffix = uuid4().hex
        payload = {
            "attraction_id": "guanlin-main",
            "slot_id": slot["id"],
            "visitor_reference": f"shared-{suffix}",
            "quantity": 2,
        }
        request_headers = {**auth(), "Idempotency-Key": f"mysql-shared-{suffix}"}

        created = client.post(f"{api_a}/v1/reservations", headers=request_headers, json=payload)
        assert created.status_code == 201

        replay = client.post(f"{api_b}/v1/reservations", headers=request_headers, json=payload)
        assert replay.status_code == 200
        assert replay.json()["id"] == created.json()["id"]

        seen_from_b = client.get(
            f"{api_b}/v1/slots",
            params={"attraction_id": "guanlin-main"},
            headers=auth(),
        ).json()[0]
        assert seen_from_b["remaining_capacity"] == slot["remaining_capacity"] - 2

        race_visitor = f"race-{suffix}"

        def reserve(base_url: str, key: str) -> int:
            response = httpx.post(
                f"{base_url}/v1/reservations",
                headers={**auth(), "Idempotency-Key": key},
                json={**payload, "visitor_reference": race_visitor, "quantity": 1},
                timeout=10,
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(
                pool.map(
                    lambda args: reserve(*args),
                    ((api_a, f"race-a-{suffix}"), (api_b, f"race-b-{suffix}")),
                )
            )
        assert sorted(statuses) == [201, 409]

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
import time
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


def test_consumer_pause_and_drain_are_shared_across_api_instances():
    api_a = os.getenv("HERITAGEFLOW_INTEGRATION_MYSQL_API_A")
    api_b = os.getenv("HERITAGEFLOW_INTEGRATION_MYSQL_API_B")
    if not api_a or not api_b:
        pytest.skip("MySQL API integration endpoints are not configured")

    admin_headers = auth("tenant_admin")
    suffix = uuid4().hex
    with httpx.Client(timeout=10) as client:
        client.post(f"{api_a}/v1/admin/consumer/resume", headers=admin_headers).raise_for_status()
        deadline = time.monotonic() + 5
        while True:
            baseline = client.get(f"{api_b}/v1/admin/consumer", headers=admin_headers).json()
            if baseline["queue_depth"] == 0:
                break
            if time.monotonic() >= deadline:
                pytest.fail(f"consumer did not reach an empty baseline: {baseline}")
            time.sleep(0.05)

        slot_response = client.post(
            f"{api_a}/v1/admin/slots",
            headers=admin_headers,
            json={
                "attraction_id": "guanlin-main",
                "starts_at": "2033-01-01T09:00:00Z",
                "ends_at": "2033-01-01T10:00:00Z",
                "capacity": 5,
            },
        )
        assert slot_response.status_code == 201, slot_response.text
        slot_id = slot_response.json()["id"]

        pause = client.post(f"{api_a}/v1/admin/consumer/pause", headers=admin_headers)
        assert pause.status_code == 200
        try:
            for index in range(5):
                base_url = api_a if index % 2 == 0 else api_b
                response = client.post(
                    f"{base_url}/v1/reservations",
                    headers={**auth(), "Idempotency-Key": f"mysql-outbox-{suffix}-{index}"},
                    json={
                        "attraction_id": "guanlin-main",
                        "slot_id": slot_id,
                        "visitor_reference": f"mysql-outbox-{suffix}-{index}",
                        "quantity": 1,
                    },
                )
                assert response.status_code == 201, response.text

            accumulated = client.get(
                f"{api_b}/v1/admin/consumer", headers=admin_headers
            ).json()
            assert accumulated["paused"] is True
            assert accumulated["queue_depth"] == 5

            resumed = client.post(f"{api_b}/v1/admin/consumer/resume", headers=admin_headers)
            assert resumed.status_code == 200
            deadline = time.monotonic() + 5
            while True:
                final = client.get(f"{api_a}/v1/admin/consumer", headers=admin_headers).json()
                if final["queue_depth"] == 0:
                    break
                if time.monotonic() >= deadline:
                    pytest.fail(f"consumer did not drain: {final}")
                time.sleep(0.05)

            assert final["processed_total"] - baseline["processed_total"] == 5
            assert final["enqueued_total"] - baseline["enqueued_total"] == 5
        finally:
            client.post(f"{api_b}/v1/admin/consumer/resume", headers=admin_headers)

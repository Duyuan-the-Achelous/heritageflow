from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from heritageflow.config import Settings
from heritageflow.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        environment="development",
        database_path=tmp_path / "test.db",
        visitor_hash_key="test-only-hash-key",
        api_keys={},
    )
    return TestClient(create_app(settings))


def auth(tenant: str, role: str = "visitor") -> dict[str, str]:
    return {"Authorization": f"Bearer demo:{tenant}:{role}"}


def create_slot(client: TestClient, tenant: str, attraction: str, capacity: int) -> str:
    response = client.post(
        "/v1/admin/slots",
        headers=auth(tenant, "tenant_admin"),
        json={
            "attraction_id": attraction,
            "starts_at": "2030-01-01T09:00:00Z",
            "ends_at": "2030-01-01T10:00:00Z",
            "capacity": capacity,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def reserve(client: TestClient, tenant: str, attraction: str, slot: str, key: str):
    return client.post(
        "/v1/reservations",
        headers={**auth(tenant), "Idempotency-Key": key},
        json={
            "attraction_id": attraction,
            "slot_id": slot,
            "visitor_reference": f"visitor-{key}",
            "quantity": 1,
        },
    )


def test_idempotency_does_not_consume_capacity_twice(tmp_path: Path):
    with make_client(tmp_path) as client:
        slot = create_slot(client, "guanlin", "guanlin-main", 2)
        first = reserve(client, "guanlin", "guanlin-main", slot, "same-key-001")
        second = reserve(client, "guanlin", "guanlin-main", slot, "same-key-001")

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        slots = client.get(
            "/v1/slots",
            headers=auth("guanlin"),
            params={"attraction_id": "guanlin-main"},
        ).json()
        created_slot = next(item for item in slots if item["id"] == slot)
        assert created_slot["remaining_capacity"] == 1


def test_same_visitor_cannot_book_same_slot_twice(tmp_path: Path):
    with make_client(tmp_path) as client:
        slot = create_slot(client, "guanlin", "guanlin-main", 3)
        first = reserve(client, "guanlin", "guanlin-main", slot, "visitor-one")
        duplicate = client.post(
            "/v1/reservations",
            headers={**auth("guanlin"), "Idempotency-Key": "different-key-002"},
            json={
                "attraction_id": "guanlin-main",
                "slot_id": slot,
                "visitor_reference": "visitor-visitor-one",
                "quantity": 1,
            },
        )

        assert first.status_code == 201
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "visitor already has an active reservation for this slot"


def test_cancelled_visitor_can_book_same_slot_again(tmp_path: Path):
    with make_client(tmp_path) as client:
        slot = create_slot(client, "guanlin", "guanlin-main", 2)
        first = reserve(client, "guanlin", "guanlin-main", slot, "rebook-001").json()
        cancelled = client.post(
            f"/v1/reservations/{first['id']}/cancel",
            headers=auth("guanlin"),
        )
        second = client.post(
            "/v1/reservations",
            headers={**auth("guanlin"), "Idempotency-Key": "rebook-002"},
            json={
                "attraction_id": "guanlin-main",
                "slot_id": slot,
                "visitor_reference": "visitor-rebook-001",
                "quantity": 1,
            },
        )

        assert cancelled.status_code == 200
        assert second.status_code == 201


def test_cross_tenant_access_is_hidden(tmp_path: Path):
    with make_client(tmp_path) as client:
        slot = create_slot(client, "guanlin", "guanlin-main", 1)
        reservation = reserve(client, "guanlin", "guanlin-main", slot, "tenant-test-001").json()

        response = client.get(
            f"/v1/reservations/{reservation['id']}",
            headers=auth("tomb-museum"),
        )
        assert response.status_code == 404


def test_concurrent_reservations_never_oversell(tmp_path: Path):
    client = make_client(tmp_path)
    with client:
        slot = create_slot(client, "tomb-museum", "tomb-museum-main", 10)

        def attempt(index: int) -> int:
            return reserve(
                client,
                "tomb-museum",
                "tomb-museum-main",
                slot,
                f"oversell-{index:03d}",
            ).status_code

        with ThreadPoolExecutor(max_workers=25) as pool:
            statuses = list(pool.map(attempt, range(50)))

        assert statuses.count(201) == 10
        assert statuses.count(409) == 40
        slots = client.get(
            "/v1/slots",
            headers=auth("tomb-museum"),
            params={"attraction_id": "tomb-museum-main"},
        ).json()
        created_slot = next(item for item in slots if item["id"] == slot)
        assert created_slot["remaining_capacity"] == 0


def test_validation_is_single_use_and_tenant_scoped(tmp_path: Path):
    with make_client(tmp_path) as client:
        slot = create_slot(client, "wanan-mountain", "wanan-canyon", 1)
        reservation = reserve(
            client,
            "wanan-mountain",
            "wanan-canyon",
            slot,
            "validate-001",
        ).json()

        wrong_tenant = client.post(
            "/v1/validations",
            headers=auth("guanlin", "validator"),
            json={"validation_code": reservation["validation_code"]},
        )
        first = client.post(
            "/v1/validations",
            headers=auth("wanan-mountain", "validator"),
            json={"validation_code": reservation["validation_code"]},
        )
        second = client.post(
            "/v1/validations",
            headers=auth("wanan-mountain", "validator"),
            json={"validation_code": reservation["validation_code"]},
        )

        assert wrong_tenant.status_code == 404
        assert first.status_code == 200
        assert first.json()["status"] == "validated"
        assert second.status_code == 409


def test_cancel_restores_capacity_and_cannot_cancel_validated(tmp_path: Path):
    with make_client(tmp_path) as client:
        slot = create_slot(client, "guanlin", "guanlin-main", 2)
        reservation = reserve(client, "guanlin", "guanlin-main", slot, "cancel-001").json()
        cancelled = client.post(
            f"/v1/reservations/{reservation['id']}/cancel",
            headers=auth("guanlin"),
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        slots = client.get(
            "/v1/slots",
            headers=auth("guanlin"),
            params={"attraction_id": "guanlin-main"},
        ).json()
        created_slot = next(item for item in slots if item["id"] == slot)
        assert created_slot["remaining_capacity"] == 2


def test_readiness_checks_storage_and_returns_request_id(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.get("/ready", headers={"X-Request-ID": "course-demo-001"})

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        assert response.headers["X-Request-ID"] == "course-demo-001"


def test_invalid_request_id_is_replaced(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.get("/health", headers={"X-Request-ID": "contains spaces"})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] != "contains spaces"
        assert len(response.headers["X-Request-ID"]) == 32


def test_frontend_is_served(tmp_path: Path):
    with make_client(tmp_path) as client:
        page = client.get("/")
        script = client.get("/static/app.js")

        assert page.status_code == 200
        assert "河洛行" in page.text
        assert script.status_code == 200
        assert "createReservation" in script.text

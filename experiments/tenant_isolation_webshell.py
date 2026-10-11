from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = os.getenv("E4_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
RESULT_PATH = Path("/tmp/e4-tenant-isolation-result.json")
TENANTS = {
    "guanlin": "guanlin-main",
    "tomb-museum": "tomb-museum-main",
    "wanan-mountain": "wanan-canyon",
}


def request(
    method: str,
    path: str,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(f"{BASE_URL}{path}", data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def configured_tokens() -> dict[str, str]:
    mappings = json.loads(os.environ["HERITAGEFLOW_API_KEYS_JSON"])
    tokens = {
        principal["tenant_id"]: token
        for token, principal in mappings.items()
        if principal.get("role") in {"tenant_admin", "platform_admin"}
    }
    missing = sorted(set(TENANTS) - set(tokens))
    if missing:
        raise RuntimeError(f"missing admin token mappings for: {missing}")
    return tokens


def leaked(body: Any) -> bool:
    sensitive = {"id", "tenant_id", "slot_id", "validation_code"}
    return isinstance(body, dict) and bool(sensitive.intersection(body))


def main() -> int:
    tokens = configured_tokens()
    started = datetime.now(UTC)
    pairs: list[dict[str, Any]] = []
    owner_checks: list[dict[str, Any]] = []
    list_route_statuses: set[int] = set()

    for owner_index, (owner, attraction) in enumerate(TENANTS.items()):
        foreign_tenants = [tenant for tenant in TENANTS if tenant != owner]
        slot_status, slot = request(
            "POST",
            "/v1/admin/slots",
            tokens[owner],
            {
                "attraction_id": attraction,
                "starts_at": f"2035-06-03T{9 + owner_index:02d}:00:00Z",
                "ends_at": f"2035-06-03T{10 + owner_index:02d}:00:00Z",
                "capacity": 3,
            },
        )
        if slot_status != 201:
            raise RuntimeError(f"slot creation failed for {owner}: {slot_status} {slot}")

        tampered_tenant = foreign_tenants[0]
        create_status, reservation = request(
            "POST",
            "/v1/reservations",
            tokens[owner],
            {
                "attraction_id": attraction,
                "slot_id": slot["id"],
                "visitor_reference": f"e4-isolation-{owner}",
                "quantity": 1,
                "tenant_id": tampered_tenant,
            },
            f"e4-isolation-{owner}-001",
        )
        if create_status != 201:
            raise RuntimeError(f"reservation creation failed for {owner}: {create_status} {reservation}")

        list_status, list_body = request("GET", "/v1/reservations", tokens[owner])
        owner_reservations = list_body if isinstance(list_body, list) else []
        list_route_statuses.add(list_status)

        for foreign in foreign_tenants:
            query = urlencode({"attraction_id": attraction})
            slots_status, visible_slots = request(
                "GET", f"/v1/slots?{query}", tokens[foreign]
            )
            foreign_list_status, foreign_reservations = request(
                "GET", "/v1/reservations", tokens[foreign]
            )
            foreign_reservations = (
                foreign_reservations if isinstance(foreign_reservations, list) else []
            )
            list_route_statuses.add(foreign_list_status)
            read_status, read_body = request(
                "GET", f"/v1/reservations/{reservation['id']}", tokens[foreign]
            )
            cancel_status, cancel_body = request(
                "POST", f"/v1/reservations/{reservation['id']}/cancel", tokens[foreign]
            )
            validation_status, validation_body = request(
                "POST",
                "/v1/validations",
                tokens[foreign],
                {"validation_code": reservation["validation_code"]},
            )
            unauthenticated_status, unauthenticated_body = request(
                "GET", f"/v1/reservations/{reservation['id']}"
            )
            pairs.append(
                {
                    "owner": owner,
                    "foreign_tenant": foreign,
                    "foreign_slot_list_status": slots_status,
                    "owner_slot_visible_to_foreign_tenant": any(
                        item.get("id") == slot["id"] for item in visible_slots
                    ),
                    "foreign_reservation_list_status": foreign_list_status,
                    "owner_reservation_visible_to_foreign_tenant": any(
                        item.get("id") == reservation["id"] for item in foreign_reservations
                    ),
                    "foreign_list_contains_only_foreign_tenant": all(
                        item.get("tenant_id") == foreign for item in foreign_reservations
                    ),
                    "foreign_read_status": read_status,
                    "foreign_cancel_status": cancel_status,
                    "foreign_validation_status": validation_status,
                    "unauthenticated_read_status": unauthenticated_status,
                    "foreign_response_leaked_reservation_fields": any(
                        leaked(body)
                        for body in (read_body, cancel_body, validation_body, unauthenticated_body)
                    ),
                }
            )

        owner_read_status, owner_reservation = request(
            "GET", f"/v1/reservations/{reservation['id']}", tokens[owner]
        )
        owner_checks.append(
            {
                "owner": owner,
                "tampered_tenant_id": tampered_tenant,
                "response_tenant_id": reservation["tenant_id"],
                "body_tenant_ignored": reservation["tenant_id"] == owner,
                "owner_reservation_list_status": list_status,
                "owner_reservation_visible_in_owner_list": any(
                    item.get("id") == reservation["id"] for item in owner_reservations
                ),
                "owner_list_contains_only_owner_tenant": all(
                    item.get("tenant_id") == owner for item in owner_reservations
                ),
                "owner_read_status_after_foreign_attempts": owner_read_status,
                "reservation_status_after_foreign_attempts": owner_reservation.get("status"),
            }
        )

    pair_matrix_passed = all(
        item["foreign_slot_list_status"] == 200
        and not item["owner_slot_visible_to_foreign_tenant"]
        and item["foreign_reservation_list_status"] == 200
        and not item["owner_reservation_visible_to_foreign_tenant"]
        and item["foreign_list_contains_only_foreign_tenant"]
        and item["foreign_read_status"] == 404
        and item["foreign_cancel_status"] == 404
        and item["foreign_validation_status"] == 404
        and item["unauthenticated_read_status"] == 401
        and not item["foreign_response_leaked_reservation_fields"]
        for item in pairs
    )
    owner_checks_passed = all(
        item["body_tenant_ignored"]
        and item["owner_reservation_list_status"] == 200
        and item["owner_reservation_visible_in_owner_list"]
        and item["owner_list_contains_only_owner_tenant"]
        and item["owner_read_status_after_foreign_attempts"] == 200
        and item["reservation_status_after_foreign_attempts"] == "confirmed"
        for item in owner_checks
    )
    reservation_list_route_available = list_route_statuses == {200}
    result = {
        "experiment": "e4-tenant-isolation",
        "environment": "alibaba-cloud-sae-production",
        "base_url": BASE_URL,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "tenant_pair_count": len(pairs),
        "pair_results": pairs,
        "owner_checks": owner_checks,
        "reservation_list_route_statuses": sorted(list_route_statuses),
        "pair_matrix_passed": pair_matrix_passed,
        "owner_checks_passed": owner_checks_passed,
        "reservation_list_route_available": reservation_list_route_available,
        "passed_for_implemented_surfaces": pair_matrix_passed and owner_checks_passed,
        "course_requirement_complete": (
            pair_matrix_passed and owner_checks_passed and reservation_list_route_available
        ),
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["course_requirement_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

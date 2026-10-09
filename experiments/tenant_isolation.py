from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from common import auth, create_slot, metadata, output_path, require_status, write_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise tenant isolation through the public API.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        slot = create_slot(client, "guanlin", "guanlin-main", 3)
        created = client.post(
            "/v1/reservations",
            headers={**auth("guanlin"), "Idempotency-Key": f"isolation-{slot['id']}"},
            json={
                "attraction_id": "guanlin-main",
                "slot_id": slot["id"],
                "visitor_reference": "synthetic-isolation-subject",
                "quantity": 1,
                "tenant_id": "tomb-museum",
            },
        )
        require_status(created, 201)
        reservation = created.json()

        checks = {
            "unauthenticated_read": client.get(f"/v1/reservations/{reservation['id']}").status_code,
            "foreign_read": client.get(
                f"/v1/reservations/{reservation['id']}", headers=auth("tomb-museum")
            ).status_code,
            "foreign_cancel": client.post(
                f"/v1/reservations/{reservation['id']}/cancel", headers=auth("tomb-museum")
            ).status_code,
            "foreign_validation": client.post(
                "/v1/validations",
                headers=auth("tomb-museum", "validator"),
                json={"validation_code": reservation["validation_code"]},
            ).status_code,
            "owner_read": client.get(
                f"/v1/reservations/{reservation['id']}", headers=auth("guanlin")
            ).status_code,
        }

    expected = {
        "unauthenticated_read": 401,
        "foreign_read": 404,
        "foreign_cancel": 404,
        "foreign_validation": 404,
        "owner_read": 200,
    }
    passed = checks == expected and reservation["tenant_id"] == "guanlin"
    result = {
        **metadata("tenant-isolation"),
        "metrics": {
            **checks,
            "body_tenant_ignored": reservation["tenant_id"] == "guanlin",
        },
        "passed": passed,
    }
    write_result(output_path(args.output, "tenant-isolation"), result)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

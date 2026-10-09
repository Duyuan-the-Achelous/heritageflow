from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from common import auth, create_slot, find_slot, metadata, output_path, write_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify idempotent reservation retry behavior.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        slot = create_slot(client, "wanan-mountain", "wanan-canyon", 10)
        key = f"retry-{slot['id']}"
        responses = [
            client.post(
                "/v1/reservations",
                headers={**auth("wanan-mountain"), "Idempotency-Key": key},
                json={
                    "attraction_id": "wanan-canyon",
                    "slot_id": slot["id"],
                    "visitor_reference": "synthetic-retry-subject",
                    "quantity": 1,
                },
            )
            for _ in range(args.retries)
        ]
        final_slot = find_slot(client, "wanan-mountain", "wanan-canyon", slot["id"])

    statuses = [response.status_code for response in responses]
    reservation_ids = {response.json().get("id") for response in responses if response.is_success}
    passed = (
        statuses == [201] + [200] * (args.retries - 1)
        and len(reservation_ids) == 1
        and final_slot["remaining_capacity"] == 9
    )
    result = {
        **metadata("idempotency-retry"),
        "parameters": {"attempts": args.retries},
        "metrics": {
            "created_responses": statuses.count(201),
            "replayed_responses": statuses.count(200),
            "unique_reservations": len(reservation_ids),
            "remaining_capacity": final_slot["remaining_capacity"],
        },
        "passed": passed,
    }
    write_result(output_path(args.output, "idempotency-retry"), result)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

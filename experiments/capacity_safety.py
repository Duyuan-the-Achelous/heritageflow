from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from common import auth, create_slot, find_slot, metadata, output_path, write_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify that concurrent demand cannot oversell a slot.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--attempts", type=int, default=100)
    parser.add_argument("--capacity", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        slot = create_slot(client, "guanlin", "guanlin-main", args.capacity)

        def reserve(index: int) -> int:
            response = client.post(
                "/v1/reservations",
                headers={**auth("guanlin"), "Idempotency-Key": f"capacity-{slot['id']}-{index:03d}"},
                json={
                    "attraction_id": "guanlin-main",
                    "slot_id": slot["id"],
                    "visitor_reference": f"synthetic-capacity-{index:03d}",
                    "quantity": 1,
                },
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=min(args.attempts, 100)) as pool:
            statuses = list(pool.map(reserve, range(args.attempts)))
        final_slot = find_slot(client, "guanlin", "guanlin-main", slot["id"])

    counts = Counter(statuses)
    expected_confirmed = min(args.capacity, args.attempts)
    passed = (
        counts[201] == expected_confirmed
        and counts[409] == args.attempts - expected_confirmed
        and final_slot["remaining_capacity"] == args.capacity - expected_confirmed
        and set(counts).issubset({201, 409})
    )
    result = {
        **metadata("capacity-safety"),
        "parameters": {"attempts": args.attempts, "capacity": args.capacity},
        "metrics": {
            "confirmed": counts[201],
            "capacity_rejected": counts[409],
            "unexpected_statuses": sum(value for key, value in counts.items() if key not in {201, 409}),
            "remaining_capacity": final_slot["remaining_capacity"],
        },
        "passed": passed,
    }
    write_result(output_path(args.output, "capacity-safety"), result)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

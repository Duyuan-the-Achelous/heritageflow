from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


BASE_URL = os.getenv("E6_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TENANT_ID = os.getenv("E6_TENANT_ID", "guanlin")
ATTRACTION_ID = os.getenv("E6_ATTRACTION_ID", "guanlin-main")
WORKLOAD_SIZE = int(os.getenv("E6_WORKLOAD_SIZE", "50"))
OUTAGE_SECONDS = float(os.getenv("E6_OUTAGE_SECONDS", "15"))
RESULT_PATH = Path("/tmp/e6-async-consumer-outage-result.json")


def request(
    method: str,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request_headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    req = Request(f"{BASE_URL}{path}", data=data, headers=request_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            body_data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body_data = raw
        return exc.code, body_data


def tenant_admin_token() -> str:
    configured = json.loads(os.environ["HERITAGEFLOW_API_KEYS_JSON"])
    for token, principal in configured.items():
        if principal.get("tenant_id") == TENANT_ID and principal.get("role") in {
            "platform_admin",
            "tenant_admin",
        }:
            return token
    raise RuntimeError(f"no admin token configured for tenant {TENANT_ID}")


def require_status(actual: int, expected: int, operation: str, body: Any) -> None:
    if actual != expected:
        raise RuntimeError(f"{operation} failed: HTTP {actual} {body}")


def wait_until_drained(token: str, timeout_seconds: float = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        status, body = request("GET", "/v1/admin/consumer", token)
        require_status(status, 200, "consumer status", body)
        if body["queue_depth"] == 0:
            return body
        if time.monotonic() >= deadline:
            raise RuntimeError(f"consumer did not drain before timeout: {body}")
        time.sleep(0.25)


def main() -> int:
    token = tenant_admin_token()
    started = datetime.now(UTC)
    run_id = uuid4().hex
    paused = False
    try:
        resume_status, resume_body = request("POST", "/v1/admin/consumer/resume", token)
        require_status(resume_status, 200, "initial consumer resume", resume_body)
        baseline = wait_until_drained(token)

        slot_status, slot = request(
            "POST",
            "/v1/admin/slots",
            token,
            {
                "attraction_id": ATTRACTION_ID,
                "starts_at": "2032-06-01T09:00:00Z",
                "ends_at": "2032-06-01T10:00:00Z",
                "capacity": WORKLOAD_SIZE,
            },
        )
        require_status(slot_status, 201, "slot creation", slot)

        pause_status, pause_body = request("POST", "/v1/admin/consumer/pause", token)
        require_status(pause_status, 200, "consumer pause", pause_body)
        paused = True

        def create_reservation(index: int) -> tuple[int, Any]:
            return request(
                "POST",
                "/v1/reservations",
                token,
                {
                    "attraction_id": ATTRACTION_ID,
                    "slot_id": slot["id"],
                    "visitor_reference": f"e6-{run_id}-{index:04d}",
                    "quantity": 1,
                },
                {"Idempotency-Key": f"e6-{run_id}-{index:04d}"},
            )

        with ThreadPoolExecutor(max_workers=min(20, WORKLOAD_SIZE)) as pool:
            responses = list(pool.map(create_reservation, range(WORKLOAD_SIZE)))
        creation_status_counts: dict[str, int] = {}
        for status, _body in responses:
            key = str(status)
            creation_status_counts[key] = creation_status_counts.get(key, 0) + 1

        accumulated_status, accumulated = request("GET", "/v1/admin/consumer", token)
        require_status(accumulated_status, 200, "accumulated consumer status", accumulated)
        time.sleep(OUTAGE_SECONDS)
        aged_status, aged = request("GET", "/v1/admin/consumer", token)
        require_status(aged_status, 200, "aged consumer status", aged)

        drain_started = time.monotonic()
        restore_status, restore_body = request("POST", "/v1/admin/consumer/resume", token)
        require_status(restore_status, 200, "consumer resume", restore_body)
        paused = False
        final = wait_until_drained(token)
        drain_seconds = time.monotonic() - drain_started

        enqueued_delta = final["enqueued_total"] - baseline["enqueued_total"]
        processed_delta = final["processed_total"] - baseline["processed_total"]
        passed = all(
            (
                creation_status_counts == {"201": WORKLOAD_SIZE},
                accumulated["paused"] is True,
                accumulated["queue_depth"] == WORKLOAD_SIZE,
                aged["queue_depth"] == WORKLOAD_SIZE,
                aged["oldest_message_age_seconds"] >= max(0, OUTAGE_SECONDS - 1),
                enqueued_delta == WORKLOAD_SIZE,
                processed_delta == WORKLOAD_SIZE,
                final["queue_depth"] == 0,
                final["paused"] is False,
            )
        )
        result = {
            "experiment": "e6-async-consumer-outage",
            "environment": "alibaba-cloud-sae-production",
            "base_url": BASE_URL,
            "tenant_id": TENANT_ID,
            "started_at_utc": started.isoformat(),
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "parameters": {"workload_size": WORKLOAD_SIZE, "outage_seconds": OUTAGE_SECONDS},
            "creation_status_counts": creation_status_counts,
            "baseline": baseline,
            "accumulated": accumulated,
            "aged": aged,
            "final": final,
            "metrics": {
                "enqueued_delta": enqueued_delta,
                "processed_delta": processed_delta,
                "drain_seconds": round(drain_seconds, 3),
            },
            "passed": passed,
        }
        RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0 if passed else 1
    finally:
        if paused:
            request("POST", "/v1/admin/consumer/resume", token)


if __name__ == "__main__":
    raise SystemExit(main())

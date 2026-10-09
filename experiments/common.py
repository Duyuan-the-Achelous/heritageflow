from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def auth(tenant: str, role: str = "visitor") -> dict[str, str]:
    return {"Authorization": f"Bearer demo:{tenant}:{role}"}


def require_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}, expected {expected}: {response.text}"
        )


def create_slot(
    client: httpx.Client,
    tenant: str,
    attraction: str,
    capacity: int,
) -> dict[str, Any]:
    response = client.post(
        "/v1/admin/slots",
        headers=auth(tenant, "tenant_admin"),
        json={
            "attraction_id": attraction,
            "starts_at": "2035-06-01T09:00:00Z",
            "ends_at": "2035-06-01T10:00:00Z",
            "capacity": capacity,
        },
    )
    require_status(response, 201)
    return response.json()


def find_slot(
    client: httpx.Client,
    tenant: str,
    attraction: str,
    slot_id: str,
) -> dict[str, Any]:
    response = client.get(
        "/v1/slots",
        headers=auth(tenant),
        params={"attraction_id": attraction},
    )
    require_status(response, 200)
    return next(slot for slot in response.json() if slot["id"] == slot_id)


def metadata(experiment: str) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "experiment": experiment,
        "environment": "local-engineering-baseline",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": commit,
    }


def output_path(requested: Path | None, experiment: str) -> Path:
    if requested:
        return requested
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("results/.local") / f"{experiment}-{stamp}.json"


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path.resolve())

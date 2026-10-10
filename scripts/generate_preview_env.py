from __future__ import annotations

import json
import secrets
from pathlib import Path


OUTPUT = Path(".env.preview")
TENANTS = {
    "guanlin": "tenant_admin",
    "tomb-museum": "tenant_admin",
    "wanan-mountain": "tenant_admin",
}


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} already exists; refusing to overwrite secrets")

    tokens = {tenant: secrets.token_urlsafe(24) for tenant in TENANTS}
    api_keys = {
        tokens[tenant]: {"tenant_id": tenant, "role": role}
        for tenant, role in TENANTS.items()
    }
    lines = [
        f"HERITAGEFLOW_VISITOR_HASH_KEY={secrets.token_hex(32)}",
        "HERITAGEFLOW_API_KEYS_JSON="
        + json.dumps(api_keys, separators=(",", ":")),
        "",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    OUTPUT.chmod(0o600)

    print(f"Created {OUTPUT} with owner-only permissions.")
    print("Save these demo tokens somewhere private:")
    for tenant, token in tokens.items():
        print(f"  {tenant}: {token}")


if __name__ == "__main__":
    main()


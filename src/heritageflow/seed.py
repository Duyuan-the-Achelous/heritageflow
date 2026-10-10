from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta, timezone

from .config import load_settings
from .db import Database


TENANTS = [
    ("guanlin", "Luoyang Guanlin", "paid_heritage_site"),
    ("tomb-museum", "Luoyang Ancient Tomb Museum", "free_museum"),
    ("wanan-mountain", "Wan'an Mountain", "outdoor_resort"),
]

ATTRACTIONS = [
    ("guanlin-main", "guanlin", "Guanlin Scenic Area", "paid", 0, None),
    ("tomb-museum-main", "tomb-museum", "Ancient Tomb Museum", "free", 1, 3),
    ("wanan-canyon", "wanan-mountain", "Wan'an Mountain Canyon", "pass_or_paid", 0, None),
]


def seed(database: Any) -> None:
    database.initialize()
    insert_ignore = database.insert_ignore_prefix
    with database.transaction(immediate=True) as connection:
        connection.executemany(
            f"{insert_ignore} INTO tenants (id, name, tenant_type) VALUES (?, ?, ?)",
            TENANTS,
        )
        connection.executemany(
            f"""{insert_ignore} INTO attractions
               (id, tenant_id, name, admission_mode, requires_real_name, no_show_limit)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ATTRACTIONS,
        )

        tomorrow = datetime.now(timezone.utc).replace(hour=1, minute=0, second=0, microsecond=0) + timedelta(days=1)
        for attraction_id, tenant_id, _name, _mode, _real_name, _no_show_limit in ATTRACTIONS:
            slot_id = f"demo-{attraction_id}-tomorrow"
            connection.execute(
                f"""{insert_ignore} INTO slots
                   (id, tenant_id, attraction_id, starts_at, ends_at, capacity, remaining_capacity)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    slot_id,
                    tenant_id,
                    attraction_id,
                    tomorrow.isoformat(),
                    (tomorrow + timedelta(hours=8)).isoformat(),
                    100,
                    100,
                ),
            )


def main() -> None:
    settings = load_settings()
    seed(Database(settings.database_path))
    print(f"Seeded HeritageFlow database at {settings.database_path}")


if __name__ == "__main__":
    main()

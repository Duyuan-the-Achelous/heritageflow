from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tenant_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attractions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    admission_mode TEXT NOT NULL CHECK (admission_mode IN ('paid', 'free', 'pass_or_paid')),
    requires_real_name INTEGER NOT NULL CHECK (requires_real_name IN (0, 1)),
    no_show_limit INTEGER
);

CREATE TABLE IF NOT EXISTS slots (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    attraction_id TEXT NOT NULL REFERENCES attractions(id),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    remaining_capacity INTEGER NOT NULL CHECK (remaining_capacity >= 0)
);

CREATE TABLE IF NOT EXISTS reservations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    attraction_id TEXT NOT NULL REFERENCES attractions(id),
    slot_id TEXT NOT NULL REFERENCES slots(id),
    visitor_reference_hash TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled', 'validated')),
    validation_code TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cancelled_at TEXT,
    UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS validations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    reservation_id TEXT NOT NULL UNIQUE REFERENCES reservations(id),
    validated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_slots_tenant_attraction
ON slots(tenant_id, attraction_id, starts_at);

CREATE INDEX IF NOT EXISTS idx_reservations_tenant
ON reservations(tenant_id, created_at);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


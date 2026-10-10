from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Iterator

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor


MYSQL_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS tenants (
        id VARCHAR(100) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        tenant_type VARCHAR(100) NOT NULL
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS attractions (
        id VARCHAR(100) PRIMARY KEY,
        tenant_id VARCHAR(100) NOT NULL,
        name VARCHAR(255) NOT NULL,
        admission_mode ENUM('paid', 'free', 'pass_or_paid') NOT NULL,
        requires_real_name BOOLEAN NOT NULL,
        no_show_limit INT NULL,
        CONSTRAINT fk_attractions_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
        INDEX idx_attractions_tenant (tenant_id)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS slots (
        id VARCHAR(100) PRIMARY KEY,
        tenant_id VARCHAR(100) NOT NULL,
        attraction_id VARCHAR(100) NOT NULL,
        starts_at VARCHAR(40) NOT NULL,
        ends_at VARCHAR(40) NOT NULL,
        capacity INT NOT NULL,
        remaining_capacity INT NOT NULL,
        CONSTRAINT fk_slots_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
        CONSTRAINT fk_slots_attraction FOREIGN KEY (attraction_id) REFERENCES attractions(id),
        INDEX idx_slots_tenant_attraction (tenant_id, attraction_id, starts_at)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS reservations (
        id VARCHAR(100) PRIMARY KEY,
        tenant_id VARCHAR(100) NOT NULL,
        attraction_id VARCHAR(100) NOT NULL,
        slot_id VARCHAR(100) NOT NULL,
        visitor_reference_hash CHAR(64) NOT NULL,
        quantity INT NOT NULL,
        status ENUM('confirmed', 'cancelled', 'validated') NOT NULL,
        validation_code VARCHAR(200) NOT NULL UNIQUE,
        idempotency_key VARCHAR(200) NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        cancelled_at VARCHAR(40) NULL,
        active_booking_key CHAR(64) GENERATED ALWAYS AS (
            CASE WHEN status IN ('confirmed', 'validated')
            THEN SHA2(CONCAT(tenant_id, ':', slot_id, ':', visitor_reference_hash), 256)
            ELSE NULL END
        ) STORED,
        CONSTRAINT fk_reservations_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
        CONSTRAINT fk_reservations_attraction FOREIGN KEY (attraction_id) REFERENCES attractions(id),
        CONSTRAINT fk_reservations_slot FOREIGN KEY (slot_id) REFERENCES slots(id),
        UNIQUE KEY uq_reservation_idempotency (tenant_id, idempotency_key),
        UNIQUE KEY uq_active_booking (active_booking_key),
        INDEX idx_reservations_tenant (tenant_id, created_at)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS validations (
        id VARCHAR(100) PRIMARY KEY,
        tenant_id VARCHAR(100) NOT NULL,
        reservation_id VARCHAR(100) NOT NULL UNIQUE,
        validated_at VARCHAR(40) NOT NULL,
        CONSTRAINT fk_validations_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id),
        CONSTRAINT fk_validations_reservation FOREIGN KEY (reservation_id) REFERENCES reservations(id)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id VARCHAR(100) PRIMARY KEY,
        tenant_id VARCHAR(100) NOT NULL,
        event_type VARCHAR(100) NOT NULL,
        entity_id VARCHAR(100) NOT NULL,
        payload_json JSON NOT NULL,
        created_at VARCHAR(40) NOT NULL,
        INDEX idx_audit_tenant_created (tenant_id, created_at)
    ) ENGINE=InnoDB
    """,
)


def _mysql_sql(sql: str) -> str:
    return sql.replace("?", "%s")


class MySQLConnection:
    def __init__(self, connection: Connection):
        self._connection = connection

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        cursor = self._connection.cursor()
        cursor.execute(_mysql_sql(sql), parameters)
        return cursor

    def executemany(self, sql: str, parameters: Iterable[tuple[Any, ...]]) -> Any:
        cursor = self._connection.cursor()
        cursor.executemany(_mysql_sql(sql), parameters)
        return cursor

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MySQLConnection":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


class MySQLDatabase:
    insert_ignore_prefix = "INSERT IGNORE"

    def __init__(self, *, host: str, port: int, database: str, user: str, password: str):
        self.options = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": False,
            "connect_timeout": 10,
        }

    def connect(self) -> MySQLConnection:
        return MySQLConnection(pymysql.connect(**self.options))

    def initialize(self) -> None:
        with self.transaction() as connection:
            for statement in MYSQL_SCHEMA:
                connection.execute(statement)

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[MySQLConnection]:
        del immediate
        connection = self.connect()
        try:
            connection.execute("START TRANSACTION")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

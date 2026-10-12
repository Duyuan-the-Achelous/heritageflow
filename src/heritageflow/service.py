from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from pymysql.err import IntegrityError as MySQLIntegrityError


class NotFoundError(Exception):
    pass


class CapacityError(Exception):
    pass


class ConflictError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ReservationService:
    def __init__(self, database: Any, visitor_hash_key: str):
        self.database = database
        self.visitor_hash_key = visitor_hash_key.encode("utf-8")

    def hash_visitor_reference(self, value: str) -> str:
        return hmac.new(self.visitor_hash_key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def ready(self) -> None:
        with self.database.connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def list_attractions(self, tenant_id: str) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT id, tenant_id, name, admission_mode, requires_real_name, no_show_limit
                   FROM attractions WHERE tenant_id = ? ORDER BY name""",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_slots(self, tenant_id: str, attraction_id: str) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT id, attraction_id, starts_at, ends_at, capacity, remaining_capacity
                   FROM slots WHERE tenant_id = ? AND attraction_id = ? ORDER BY starts_at""",
                (tenant_id, attraction_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_slot(
        self,
        tenant_id: str,
        attraction_id: str,
        starts_at: str,
        ends_at: str,
        capacity: int,
    ) -> dict:
        slot_id = new_id("slot")
        with self.database.transaction(immediate=True) as connection:
            attraction = connection.execute(
                "SELECT id FROM attractions WHERE id = ? AND tenant_id = ?",
                (attraction_id, tenant_id),
            ).fetchone()
            if not attraction:
                raise NotFoundError("attraction not found for tenant")
            connection.execute(
                """INSERT INTO slots
                   (id, tenant_id, attraction_id, starts_at, ends_at, capacity, remaining_capacity)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (slot_id, tenant_id, attraction_id, starts_at, ends_at, capacity, capacity),
            )
        return self.get_slot(tenant_id, slot_id)

    def get_slot(self, tenant_id: str, slot_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT id, attraction_id, starts_at, ends_at, capacity, remaining_capacity
                   FROM slots WHERE id = ? AND tenant_id = ?""",
                (slot_id, tenant_id),
            ).fetchone()
        if not row:
            raise NotFoundError("slot not found")
        return dict(row)

    def create_reservation(
        self,
        tenant_id: str,
        attraction_id: str,
        slot_id: str,
        visitor_reference: str,
        quantity: int,
        idempotency_key: str,
    ) -> tuple[dict, bool]:
        try:
            return self._create_reservation_transaction(
                tenant_id,
                attraction_id,
                slot_id,
                visitor_reference,
                quantity,
                idempotency_key,
            )
        except MySQLIntegrityError as exc:
            # A second application instance can race after the initial lookup.
            # The database constraints decide the winner; an idempotency race
            # still returns the winning reservation instead of becoming a 500.
            with self.database.connect() as connection:
                existing = connection.execute(
                    """SELECT * FROM reservations
                       WHERE tenant_id = ? AND idempotency_key = ?""",
                    (tenant_id, idempotency_key),
                ).fetchone()
            if existing:
                return dict(existing), False
            raise ConflictError("visitor already has an active reservation for this slot") from exc

    def _create_reservation_transaction(
        self,
        tenant_id: str,
        attraction_id: str,
        slot_id: str,
        visitor_reference: str,
        quantity: int,
        idempotency_key: str,
    ) -> tuple[dict, bool]:
        with self.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                """SELECT * FROM reservations
                   WHERE tenant_id = ? AND idempotency_key = ?""",
                (tenant_id, idempotency_key),
            ).fetchone()
            if existing:
                return dict(existing), False

            visitor_reference_hash = self.hash_visitor_reference(visitor_reference)
            duplicate = connection.execute(
                """SELECT id FROM reservations
                   WHERE tenant_id = ? AND slot_id = ? AND visitor_reference_hash = ?
                     AND status IN ('confirmed', 'validated')
                   LIMIT 1""",
                (tenant_id, slot_id, visitor_reference_hash),
            ).fetchone()
            if duplicate:
                raise ConflictError("visitor already has an active reservation for this slot")

            slot = connection.execute(
                """SELECT id FROM slots
                   WHERE id = ? AND tenant_id = ? AND attraction_id = ?""",
                (slot_id, tenant_id, attraction_id),
            ).fetchone()
            if not slot:
                raise NotFoundError("slot not found for tenant and attraction")

            updated = connection.execute(
                """UPDATE slots
                   SET remaining_capacity = remaining_capacity - ?
                   WHERE id = ? AND tenant_id = ? AND remaining_capacity >= ?""",
                (quantity, slot_id, tenant_id, quantity),
            )
            if updated.rowcount != 1:
                raise CapacityError("insufficient remaining capacity")

            reservation_id = new_id("res")
            created_at = utc_now()
            validation_code = secrets.token_urlsafe(18)
            connection.execute(
                """INSERT INTO reservations
                   (id, tenant_id, attraction_id, slot_id, visitor_reference_hash,
                    quantity, status, validation_code, idempotency_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?)""",
                (
                    reservation_id,
                    tenant_id,
                    attraction_id,
                    slot_id,
                    visitor_reference_hash,
                    quantity,
                    validation_code,
                    idempotency_key,
                    created_at,
                ),
            )
            self._write_audit(
                connection,
                tenant_id,
                "reservation.created",
                reservation_id,
                {"slot_id": slot_id, "quantity": quantity},
            )
            row = connection.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
            return dict(row), True

    def get_reservation(self, tenant_id: str, reservation_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reservations WHERE id = ? AND tenant_id = ?",
                (reservation_id, tenant_id),
            ).fetchone()
        if not row:
            raise NotFoundError("reservation not found")
        return dict(row)

    def list_reservations(self, tenant_id: str) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT id, tenant_id, attraction_id, slot_id, quantity, status,
                          validation_code, created_at
                   FROM reservations
                   WHERE tenant_id = ?
                   ORDER BY created_at DESC, id DESC""",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_reservation(self, tenant_id: str, reservation_id: str) -> dict:
        with self.database.transaction(immediate=True) as connection:
            reservation = connection.execute(
                "SELECT * FROM reservations WHERE id = ? AND tenant_id = ?",
                (reservation_id, tenant_id),
            ).fetchone()
            if not reservation:
                raise NotFoundError("reservation not found")
            if reservation["status"] == "cancelled":
                return dict(reservation)
            if reservation["status"] == "validated":
                raise ConflictError("validated reservation cannot be cancelled")

            cancelled_at = utc_now()
            connection.execute(
                "UPDATE reservations SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
                (cancelled_at, reservation_id),
            )
            connection.execute(
                "UPDATE slots SET remaining_capacity = remaining_capacity + ? WHERE id = ? AND tenant_id = ?",
                (reservation["quantity"], reservation["slot_id"], tenant_id),
            )
            self._write_audit(
                connection,
                tenant_id,
                "reservation.cancelled",
                reservation_id,
                {"slot_id": reservation["slot_id"], "quantity": reservation["quantity"]},
            )
            row = connection.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
            return dict(row)

    def validate_admission(self, tenant_id: str, validation_code: str) -> dict:
        with self.database.transaction(immediate=True) as connection:
            reservation = connection.execute(
                "SELECT * FROM reservations WHERE validation_code = ? AND tenant_id = ?",
                (validation_code, tenant_id),
            ).fetchone()
            if not reservation:
                raise NotFoundError("validation code not found")
            if reservation["status"] != "confirmed":
                raise ConflictError(f"reservation is already {reservation['status']}")

            validation_id = new_id("val")
            validated_at = utc_now()
            try:
                connection.execute(
                    """INSERT INTO validations (id, tenant_id, reservation_id, validated_at)
                       VALUES (?, ?, ?, ?)""",
                    (validation_id, tenant_id, reservation["id"], validated_at),
                )
            except (sqlite3.IntegrityError, MySQLIntegrityError) as exc:
                raise ConflictError("reservation already validated") from exc
            connection.execute(
                "UPDATE reservations SET status = 'validated' WHERE id = ?",
                (reservation["id"],),
            )
            self._write_audit(
                connection,
                tenant_id,
                "admission.validated",
                reservation["id"],
                {"validation_id": validation_id},
            )
        return {
            "reservation_id": reservation["id"],
            "status": "validated",
            "validated_at": validated_at,
        }

    def tenant_metrics(self, tenant_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT
                     SUM(CASE WHEN status IN ('confirmed', 'validated') THEN 1 ELSE 0 END) AS confirmed,
                     SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                     SUM(CASE WHEN status = 'validated' THEN 1 ELSE 0 END) AS validated,
                     SUM(CASE WHEN status IN ('confirmed', 'validated') THEN quantity ELSE 0 END) AS seats
                   FROM reservations WHERE tenant_id = ?""",
                (tenant_id,),
            ).fetchone()
        return {
            "tenant_id": tenant_id,
            "reservations_confirmed": row["confirmed"] or 0,
            "reservations_cancelled": row["cancelled"] or 0,
            "admissions_validated": row["validated"] or 0,
            "seats_reserved": row["seats"] or 0,
        }

    def set_consumer_paused(self, tenant_id: str, paused: bool) -> dict:
        updated_at = utc_now()
        with self.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT tenant_id FROM consumer_control WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE consumer_control SET paused = ?, updated_at = ? WHERE tenant_id = ?",
                    (paused, updated_at, tenant_id),
                )
            else:
                connection.execute(
                    "INSERT INTO consumer_control (tenant_id, paused, updated_at) VALUES (?, ?, ?)",
                    (tenant_id, paused, updated_at),
                )
        return self.consumer_status(tenant_id)

    def consumer_status(self, tenant_id: str) -> dict:
        with self.database.connect() as connection:
            control = connection.execute(
                "SELECT paused FROM consumer_control WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            queued = connection.execute(
                """SELECT COUNT(*) AS queue_depth, MIN(a.created_at) AS oldest_created_at
                   FROM audit_events a
                   LEFT JOIN processed_events p ON p.event_id = a.id
                   WHERE a.tenant_id = ? AND p.event_id IS NULL""",
                (tenant_id,),
            ).fetchone()
            enqueued = connection.execute(
                "SELECT COUNT(*) AS total FROM audit_events WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            processed = connection.execute(
                "SELECT COUNT(*) AS total FROM processed_events WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()

        oldest_age = 0.0
        if queued["oldest_created_at"]:
            created_at = datetime.fromisoformat(str(queued["oldest_created_at"]))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            oldest_age = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds())
        return {
            "tenant_id": tenant_id,
            "paused": bool(control["paused"]) if control else False,
            "queue_depth": int(queued["queue_depth"] or 0),
            "oldest_message_age_seconds": round(oldest_age, 3),
            "enqueued_total": int(enqueued["total"] or 0),
            "processed_total": int(processed["total"] or 0),
        }

    def process_outbox_batch(self, batch_size: int = 100) -> int:
        with self.database.transaction(immediate=True) as connection:
            rows = connection.execute(
                """SELECT a.id, a.tenant_id, a.event_type, a.entity_id,
                          a.payload_json, a.created_at
                   FROM audit_events a
                   LEFT JOIN processed_events p ON p.event_id = a.id
                   LEFT JOIN consumer_control c ON c.tenant_id = a.tenant_id
                   WHERE p.event_id IS NULL AND COALESCE(c.paused, 0) = 0
                   ORDER BY a.created_at, a.id
                   LIMIT ?""",
                (batch_size,),
            ).fetchall()
            processed_at = utc_now()
            inserted = 0
            for row in rows:
                cursor = connection.execute(
                    f"""{self.database.insert_ignore_prefix} INTO processed_events
                        (event_id, tenant_id, event_type, entity_id, payload_json,
                         created_at, processed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"],
                        row["tenant_id"],
                        row["event_type"],
                        row["entity_id"],
                        row["payload_json"],
                        row["created_at"],
                        processed_at,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def _write_audit(
        self,
        connection: Any,
        tenant_id: str,
        event_type: str,
        entity_id: str,
        payload: dict,
    ) -> None:
        connection.execute(
            """INSERT INTO audit_events
               (id, tenant_id, event_type, entity_id, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (new_id("evt"), tenant_id, event_type, entity_id, json.dumps(payload), utc_now()),
        )

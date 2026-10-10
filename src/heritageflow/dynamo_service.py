from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from .seed import ATTRACTIONS, TENANTS
from .service import CapacityError, ConflictError, NotFoundError, new_id, utc_now


class DynamoReservationService:
    """DynamoDB implementation using conditional and transactional writes."""

    def __init__(
        self,
        table_name: str,
        visitor_hash_key: str,
        region_name: str,
        endpoint_url: str | None = None,
        *,
        resource: Any | None = None,
        client: Any | None = None,
    ):
        if resource is None or client is None:
            import boto3

            resource = resource or boto3.resource(
                "dynamodb", region_name=region_name, endpoint_url=endpoint_url
            )
            client = client or boto3.client(
                "dynamodb", region_name=region_name, endpoint_url=endpoint_url
            )
        self.table_name = table_name
        self.table = resource.Table(table_name)
        self.client = client
        self.visitor_hash_key = visitor_hash_key.encode("utf-8")
        self.serializer = TypeSerializer()

    def ready(self) -> None:
        self.client.describe_table(TableName=self.table_name)

    def seed_demo_data(self) -> None:
        for tenant_id, name, tenant_type in TENANTS:
            self._put_if_absent(
                {
                    "PK": self._tenant_pk(tenant_id),
                    "SK": "META",
                    "entity_type": "tenant",
                    "id": tenant_id,
                    "name": name,
                    "tenant_type": tenant_type,
                }
            )
        for attraction_id, tenant_id, name, mode, real_name, no_show_limit in ATTRACTIONS:
            item = {
                "PK": self._tenant_pk(tenant_id),
                "SK": self._attraction_sk(attraction_id),
                "entity_type": "attraction",
                "id": attraction_id,
                "tenant_id": tenant_id,
                "name": name,
                "admission_mode": mode,
                "requires_real_name": bool(real_name),
            }
            if no_show_limit is not None:
                item["no_show_limit"] = no_show_limit
            self._put_if_absent(item)

            tomorrow = datetime.now(timezone.utc).replace(
                hour=1, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            slot_id = f"demo-{attraction_id}-tomorrow"
            self._put_if_absent(
                {
                    "PK": self._tenant_pk(tenant_id),
                    "SK": self._slot_sk(slot_id),
                    "entity_type": "slot",
                    "id": slot_id,
                    "tenant_id": tenant_id,
                    "attraction_id": attraction_id,
                    "starts_at": tomorrow.isoformat(),
                    "ends_at": (tomorrow + timedelta(hours=8)).isoformat(),
                    "capacity": 100,
                    "remaining_capacity": 100,
                }
            )

    def hash_visitor_reference(self, value: str) -> str:
        return hmac.new(self.visitor_hash_key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def list_attractions(self, tenant_id: str) -> list[dict]:
        items = self._query_prefix(tenant_id, "ATTRACTION#")
        return [self._public_attraction(item) for item in sorted(items, key=lambda item: item["name"])]

    def list_slots(self, tenant_id: str, attraction_id: str) -> list[dict]:
        response = self.table.query(
            KeyConditionExpression=Key("PK").eq(self._tenant_pk(tenant_id))
            & Key("SK").begins_with("SLOT#"),
            FilterExpression=Attr("attraction_id").eq(attraction_id),
        )
        items = list(response.get("Items", []))
        while response.get("LastEvaluatedKey"):
            response = self.table.query(
                KeyConditionExpression=Key("PK").eq(self._tenant_pk(tenant_id))
                & Key("SK").begins_with("SLOT#"),
                FilterExpression=Attr("attraction_id").eq(attraction_id),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        return [self._public_slot(item) for item in sorted(items, key=lambda item: item["starts_at"])]

    def create_slot(
        self,
        tenant_id: str,
        attraction_id: str,
        starts_at: str,
        ends_at: str,
        capacity: int,
    ) -> dict:
        attraction = self.table.get_item(
            Key={"PK": self._tenant_pk(tenant_id), "SK": self._attraction_sk(attraction_id)},
            ConsistentRead=True,
        ).get("Item")
        if not attraction:
            raise NotFoundError("attraction not found for tenant")
        slot_id = new_id("slot")
        item = {
            "PK": self._tenant_pk(tenant_id),
            "SK": self._slot_sk(slot_id),
            "entity_type": "slot",
            "id": slot_id,
            "tenant_id": tenant_id,
            "attraction_id": attraction_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "capacity": capacity,
            "remaining_capacity": capacity,
        }
        self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        return self._public_slot(item)

    def get_slot(self, tenant_id: str, slot_id: str) -> dict:
        item = self.table.get_item(
            Key={"PK": self._tenant_pk(tenant_id), "SK": self._slot_sk(slot_id)},
            ConsistentRead=True,
        ).get("Item")
        if not item:
            raise NotFoundError("slot not found")
        return self._public_slot(item)

    def create_reservation(
        self,
        tenant_id: str,
        attraction_id: str,
        slot_id: str,
        visitor_reference: str,
        quantity: int,
        idempotency_key: str,
    ) -> tuple[dict, bool]:
        existing = self._reservation_for_idempotency(tenant_id, idempotency_key)
        if existing:
            return existing, False

        visitor_reference_hash = self.hash_visitor_reference(visitor_reference)
        if self._active_reservation_for_visitor(tenant_id, slot_id, visitor_reference_hash):
            raise ConflictError("visitor already has an active reservation for this slot")

        slot_key = {"PK": self._tenant_pk(tenant_id), "SK": self._slot_sk(slot_id)}
        slot = self.table.get_item(Key=slot_key, ConsistentRead=True).get("Item")
        if not slot or slot.get("attraction_id") != attraction_id:
            raise NotFoundError("slot not found for tenant and attraction")

        reservation_id = new_id("res")
        created_at = utc_now()
        validation_code = secrets.token_urlsafe(18)
        reservation = {
            "PK": self._tenant_pk(tenant_id),
            "SK": self._reservation_sk(reservation_id),
            "entity_type": "reservation",
            "id": reservation_id,
            "tenant_id": tenant_id,
            "attraction_id": attraction_id,
            "slot_id": slot_id,
            "visitor_reference_hash": visitor_reference_hash,
            "quantity": quantity,
            "status": "confirmed",
            "validation_code": validation_code,
            "idempotency_key": idempotency_key,
            "created_at": created_at,
            "GSI1PK": f"TENANT#{tenant_id}#VALIDATION#{validation_code}",
            "GSI1SK": self._reservation_sk(reservation_id),
        }
        idempotency = {
            "PK": self._tenant_pk(tenant_id),
            "SK": self._idempotency_sk(idempotency_key),
            "entity_type": "idempotency",
            "reservation_id": reservation_id,
            "created_at": created_at,
        }
        booking = {
            "PK": self._tenant_pk(tenant_id),
            "SK": self._booking_sk(slot_id, visitor_reference_hash),
            "entity_type": "active_booking",
            "reservation_id": reservation_id,
            "created_at": created_at,
        }
        event = self._event_item(
            tenant_id,
            "reservation.created",
            reservation_id,
            {"slot_id": slot_id, "quantity": quantity},
        )

        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table_name,
                            "Key": self._serialize(slot_key),
                            "UpdateExpression": "SET remaining_capacity = remaining_capacity - :quantity",
                            "ConditionExpression": (
                                "attraction_id = :attraction AND remaining_capacity >= :quantity"
                            ),
                            "ExpressionAttributeValues": self._serialize(
                                {":quantity": quantity, ":attraction": attraction_id}
                            ),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": self._serialize(reservation),
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": self._serialize(idempotency),
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": self._serialize(booking),
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    {"Put": {"TableName": self.table_name, "Item": self._serialize(event)}},
                ]
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
                raise
            existing = self._reservation_for_idempotency(tenant_id, idempotency_key)
            if existing:
                return existing, False
            current_slot = self.table.get_item(Key=slot_key, ConsistentRead=True).get("Item")
            if not current_slot:
                raise NotFoundError("slot not found") from exc
            if int(current_slot.get("remaining_capacity", 0)) < quantity:
                raise CapacityError("insufficient remaining capacity") from exc
            raise ConflictError("visitor already has an active reservation for this slot") from exc
        return self._public_reservation(reservation), True

    def get_reservation(self, tenant_id: str, reservation_id: str) -> dict:
        return self._public_reservation(self._raw_reservation(tenant_id, reservation_id))

    def cancel_reservation(self, tenant_id: str, reservation_id: str) -> dict:
        reservation = self._raw_reservation(tenant_id, reservation_id)
        if reservation["status"] == "cancelled":
            return self._public_reservation(reservation)
        if reservation["status"] == "validated":
            raise ConflictError("validated reservation cannot be cancelled")
        cancelled_at = utc_now()
        event = self._event_item(
            tenant_id,
            "reservation.cancelled",
            reservation_id,
            {"slot_id": reservation["slot_id"], "quantity": int(reservation["quantity"])},
        )
        booking_key = {
            "PK": self._tenant_pk(tenant_id),
            "SK": self._booking_sk(
                reservation["slot_id"], reservation["visitor_reference_hash"]
            ),
        }
        booking = self.table.get_item(Key=booking_key, ConsistentRead=True).get("Item")
        release_booking = booking and booking.get("reservation_id") == reservation_id
        transaction_items = [
            {
                "Update": {
                    "TableName": self.table_name,
                    "Key": self._serialize(
                        {
                            "PK": self._tenant_pk(tenant_id),
                            "SK": self._reservation_sk(reservation_id),
                        }
                    ),
                    "UpdateExpression": "SET #status = :cancelled, cancelled_at = :at",
                    "ConditionExpression": "#status = :confirmed",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": self._serialize(
                        {
                            ":cancelled": "cancelled",
                            ":confirmed": "confirmed",
                            ":at": cancelled_at,
                        }
                    ),
                }
            },
            {
                "Update": {
                    "TableName": self.table_name,
                    "Key": self._serialize(
                        {
                            "PK": self._tenant_pk(tenant_id),
                            "SK": self._slot_sk(reservation["slot_id"]),
                        }
                    ),
                    "UpdateExpression": "ADD remaining_capacity :quantity",
                    "ExpressionAttributeValues": self._serialize(
                        {":quantity": int(reservation["quantity"])}
                    ),
                }
            },
            {"Put": {"TableName": self.table_name, "Item": self._serialize(event)}},
        ]
        if release_booking:
            transaction_items.append(
                {
                    "Delete": {
                        "TableName": self.table_name,
                        "Key": self._serialize(booking_key),
                        "ConditionExpression": "reservation_id = :reservation_id",
                        "ExpressionAttributeValues": self._serialize(
                            {":reservation_id": reservation_id}
                        ),
                    }
                }
            )
        try:
            self.client.transact_write_items(TransactItems=transaction_items)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                latest = self._raw_reservation(tenant_id, reservation_id)
                if latest["status"] == "cancelled":
                    return self._public_reservation(latest)
                raise ConflictError(f"reservation is already {latest['status']}") from exc
            raise
        return self.get_reservation(tenant_id, reservation_id)

    def validate_admission(self, tenant_id: str, validation_code: str) -> dict:
        response = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(
                f"TENANT#{tenant_id}#VALIDATION#{validation_code}"
            ),
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            raise NotFoundError("validation code not found")
        reservation = items[0]
        if reservation["status"] != "confirmed":
            raise ConflictError(f"reservation is already {reservation['status']}")
        validated_at = utc_now()
        validation_id = new_id("val")
        validation = {
            "PK": self._tenant_pk(tenant_id),
            "SK": f"VALIDATION#{reservation['id']}",
            "entity_type": "validation",
            "id": validation_id,
            "reservation_id": reservation["id"],
            "validated_at": validated_at,
        }
        event = self._event_item(
            tenant_id,
            "admission.validated",
            reservation["id"],
            {"validation_id": validation_id},
        )
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table_name,
                            "Key": self._serialize(
                                {"PK": reservation["PK"], "SK": reservation["SK"]}
                            ),
                            "UpdateExpression": "SET #status = :validated",
                            "ConditionExpression": "#status = :confirmed",
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": self._serialize(
                                {":validated": "validated", ":confirmed": "confirmed"}
                            ),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": self._serialize(validation),
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    {"Put": {"TableName": self.table_name, "Item": self._serialize(event)}},
                ]
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                raise ConflictError("reservation already validated") from exc
            raise
        return {
            "reservation_id": reservation["id"],
            "status": "validated",
            "validated_at": validated_at,
        }

    def tenant_metrics(self, tenant_id: str) -> dict:
        reservations = self._query_prefix(tenant_id, "RESERVATION#")
        active = [item for item in reservations if item["status"] in {"confirmed", "validated"}]
        return {
            "tenant_id": tenant_id,
            "reservations_confirmed": len(active),
            "reservations_cancelled": sum(item["status"] == "cancelled" for item in reservations),
            "admissions_validated": sum(item["status"] == "validated" for item in reservations),
            "seats_reserved": sum(int(item["quantity"]) for item in active),
        }

    def _raw_reservation(self, tenant_id: str, reservation_id: str) -> dict:
        item = self.table.get_item(
            Key={"PK": self._tenant_pk(tenant_id), "SK": self._reservation_sk(reservation_id)},
            ConsistentRead=True,
        ).get("Item")
        if not item:
            raise NotFoundError("reservation not found")
        return item

    def _reservation_for_idempotency(self, tenant_id: str, idempotency_key: str) -> dict | None:
        marker = self.table.get_item(
            Key={"PK": self._tenant_pk(tenant_id), "SK": self._idempotency_sk(idempotency_key)},
            ConsistentRead=True,
        ).get("Item")
        if not marker:
            return None
        return self.get_reservation(tenant_id, marker["reservation_id"])

    def _active_reservation_for_visitor(
        self, tenant_id: str, slot_id: str, visitor_reference_hash: str
    ) -> dict | None:
        for reservation in self._query_prefix(tenant_id, "RESERVATION#"):
            if (
                reservation.get("slot_id") == slot_id
                and reservation.get("visitor_reference_hash") == visitor_reference_hash
                and reservation.get("status") in {"confirmed", "validated"}
            ):
                return reservation
        return None

    def _query_prefix(self, tenant_id: str, prefix: str) -> list[dict]:
        kwargs = {
            "KeyConditionExpression": Key("PK").eq(self._tenant_pk(tenant_id))
            & Key("SK").begins_with(prefix)
        }
        response = self.table.query(**kwargs)
        items = list(response.get("Items", []))
        while response.get("LastEvaluatedKey"):
            response = self.table.query(**kwargs, ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
        return items

    def _put_if_absent(self, item: dict) -> None:
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

    def _event_item(
        self, tenant_id: str, event_type: str, entity_id: str, payload: dict
    ) -> dict:
        timestamp = utc_now()
        return {
            "PK": self._tenant_pk(tenant_id),
            "SK": f"EVENT#{timestamp}#{new_id('evt')}",
            "entity_type": "event",
            "tenant_id": tenant_id,
            "event_type": event_type,
            "entity_id": entity_id,
            "payload": payload,
            "created_at": timestamp,
        }

    def _serialize(self, values: dict) -> dict:
        return {key: self.serializer.serialize(value) for key, value in values.items()}

    @staticmethod
    def _tenant_pk(tenant_id: str) -> str:
        return f"TENANT#{tenant_id}"

    @staticmethod
    def _attraction_sk(attraction_id: str) -> str:
        return f"ATTRACTION#{attraction_id}"

    @staticmethod
    def _slot_sk(slot_id: str) -> str:
        return f"SLOT#{slot_id}"

    @staticmethod
    def _reservation_sk(reservation_id: str) -> str:
        return f"RESERVATION#{reservation_id}"

    @staticmethod
    def _idempotency_sk(key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"IDEMPOTENCY#{digest}"

    @staticmethod
    def _booking_sk(slot_id: str, visitor_reference_hash: str) -> str:
        digest = hashlib.sha256(f"{slot_id}:{visitor_reference_hash}".encode("utf-8")).hexdigest()
        return f"BOOKING#{digest}"

    @staticmethod
    def _public_attraction(item: dict) -> dict:
        return {
            "id": item["id"],
            "tenant_id": item["tenant_id"],
            "name": item["name"],
            "admission_mode": item["admission_mode"],
            "requires_real_name": bool(item["requires_real_name"]),
            "no_show_limit": item.get("no_show_limit"),
        }

    @staticmethod
    def _public_slot(item: dict) -> dict:
        return {
            "id": item["id"],
            "attraction_id": item["attraction_id"],
            "starts_at": item["starts_at"],
            "ends_at": item["ends_at"],
            "capacity": int(item["capacity"]),
            "remaining_capacity": int(item["remaining_capacity"]),
        }

    @staticmethod
    def _public_reservation(item: dict) -> dict:
        return {
            "id": item["id"],
            "tenant_id": item["tenant_id"],
            "attraction_id": item["attraction_id"],
            "slot_id": item["slot_id"],
            "quantity": int(item["quantity"]),
            "status": item["status"],
            "validation_code": item["validation_code"],
            "created_at": item["created_at"],
        }

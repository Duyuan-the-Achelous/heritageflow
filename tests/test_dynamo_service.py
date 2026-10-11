from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from heritageflow.dynamo_bootstrap import ensure_table
from heritageflow.dynamo_service import DynamoReservationService
from heritageflow.service import CapacityError, ConflictError, NotFoundError


@pytest.fixture
def service():
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="eu-west-1")
        client = boto3.client("dynamodb", region_name="eu-west-1")
        ensure_table(resource, client, "heritageflow-test")
        reservation_service = DynamoReservationService(
            table_name="heritageflow-test",
            visitor_hash_key="test-hash-key",
            region_name="eu-west-1",
            resource=resource,
            client=client,
        )
        reservation_service.seed_demo_data()
        yield reservation_service


def test_dynamo_reservation_is_idempotent_and_capacity_safe(service):
    slot = service.create_slot(
        "guanlin",
        "guanlin-main",
        "2030-01-01T09:00:00+00:00",
        "2030-01-01T10:00:00+00:00",
        1,
    )

    first, created = service.create_reservation(
        "guanlin", "guanlin-main", slot["id"], "visitor-a", 1, "same-key-001"
    )
    duplicate, duplicate_created = service.create_reservation(
        "guanlin", "guanlin-main", slot["id"], "visitor-a", 1, "same-key-001"
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate["id"] == first["id"]
    assert service.get_slot("guanlin", slot["id"])["remaining_capacity"] == 0

    with pytest.raises(CapacityError):
        service.create_reservation(
            "guanlin", "guanlin-main", slot["id"], "visitor-b", 1, "different-key-002"
        )


def test_dynamo_same_visitor_cannot_book_same_slot_twice_and_can_rebook_after_cancel(service):
    slot = service.create_slot(
        "guanlin",
        "guanlin-main",
        "2030-01-01T09:00:00+00:00",
        "2030-01-01T10:00:00+00:00",
        2,
    )
    first, _ = service.create_reservation(
        "guanlin", "guanlin-main", slot["id"], "visitor-a", 1, "first-key-001"
    )

    with pytest.raises(ConflictError, match="visitor already has"):
        service.create_reservation(
            "guanlin", "guanlin-main", slot["id"], "visitor-a", 1, "second-key-002"
        )

    service.cancel_reservation("guanlin", first["id"])
    rebooked, created = service.create_reservation(
        "guanlin", "guanlin-main", slot["id"], "visitor-a", 1, "third-key-003"
    )
    assert created is True
    assert rebooked["id"] != first["id"]


def test_dynamo_tenant_scope_and_single_use_validation(service):
    slot = service.create_slot(
        "wanan-mountain",
        "wanan-canyon",
        "2030-01-01T09:00:00+00:00",
        "2030-01-01T10:00:00+00:00",
        1,
    )
    reservation, _ = service.create_reservation(
        "wanan-mountain",
        "wanan-canyon",
        slot["id"],
        "visitor-c",
        1,
        "validation-key-001",
    )

    with pytest.raises(NotFoundError):
        service.get_reservation("guanlin", reservation["id"])
    with pytest.raises(NotFoundError):
        service.validate_admission("guanlin", reservation["validation_code"])

    result = service.validate_admission("wanan-mountain", reservation["validation_code"])
    assert result["status"] == "validated"
    with pytest.raises(ConflictError):
        service.validate_admission("wanan-mountain", reservation["validation_code"])


def test_dynamo_reservation_list_is_tenant_scoped(service):
    guanlin_slot = service.create_slot(
        "guanlin",
        "guanlin-main",
        "2030-01-01T09:00:00+00:00",
        "2030-01-01T10:00:00+00:00",
        1,
    )
    tomb_slot = service.create_slot(
        "tomb-museum",
        "tomb-museum-main",
        "2030-01-01T09:00:00+00:00",
        "2030-01-01T10:00:00+00:00",
        1,
    )
    guanlin_reservation, _ = service.create_reservation(
        "guanlin", "guanlin-main", guanlin_slot["id"], "visitor-g", 1, "list-key-g"
    )
    tomb_reservation, _ = service.create_reservation(
        "tomb-museum", "tomb-museum-main", tomb_slot["id"], "visitor-t", 1, "list-key-t"
    )

    assert [item["id"] for item in service.list_reservations("guanlin")] == [
        guanlin_reservation["id"]
    ]
    assert [item["id"] for item in service.list_reservations("tomb-museum")] == [
        tomb_reservation["id"]
    ]

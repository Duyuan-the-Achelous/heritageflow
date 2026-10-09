from __future__ import annotations

import json
import os

import boto3
from boto3.dynamodb.types import TypeDeserializer


sqs = boto3.client("sqs")
deserializer = TypeDeserializer()
queue_url = os.environ["QUEUE_URL"]


def handler(event, _context):
    forwarded = 0
    for record in event.get("Records", []):
        if record.get("eventName") not in {"INSERT", "MODIFY"}:
            continue
        image = record.get("dynamodb", {}).get("NewImage", {})
        if not image:
            continue
        item = {key: deserializer.deserialize(value) for key, value in image.items()}
        if item.get("entity_type") != "event":
            continue
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(
                {
                    "tenant_id": item["tenant_id"],
                    "event_type": item["event_type"],
                    "entity_id": item["entity_id"],
                    "payload": item.get("payload", {}),
                    "created_at": item["created_at"],
                },
                default=str,
            ),
            MessageGroupId=item["tenant_id"],
            MessageDeduplicationId=item["SK"],
        )
        forwarded += 1
    return {"forwarded": forwarded}

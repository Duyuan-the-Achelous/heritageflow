# DynamoDB data model

HeritageFlow uses a pooled single table. Every tenant-owned item has
`PK = TENANT#<tenant-id>`. Entity type and identity are encoded in `SK`; no read
path accepts an untrusted tenant ID from a request body.

![HeritageFlow DynamoDB model](diagrams/dynamodb-model.svg)

Editable source: `diagrams/dynamodb-model.mmd`.

| Entity | PK | SK | Purpose |
|---|---|---|---|
| Tenant | `TENANT#t` | `META` | Tenant name and type. |
| Attraction | `TENANT#t` | `ATTRACTION#a` | Admission profile owned by one tenant. |
| Slot | `TENANT#t` | `SLOT#s` | Capacity and remaining capacity. |
| Reservation | `TENANT#t` | `RESERVATION#r` | Confirmed, cancelled, or validated booking. |
| Idempotency marker | `TENANT#t` | `IDEMPOTENCY#sha256(key)` | Maps a retry key to exactly one reservation. |
| Validation | `TENANT#t` | `VALIDATION#r` | Records successful admission. |
| Event | `TENANT#t` | `EVENT#timestamp#id` | Streamed audit/event record. |

Reservations add `GSI1PK = TENANT#t#VALIDATION#code` and
`GSI1SK = RESERVATION#r`. The GSI supports a tenant-scoped validation-code
lookup without scanning another tenant's partition.

## Transaction invariants

1. Reservation creation succeeds only when `remaining_capacity >= quantity`.
2. Capacity decrement, reservation, idempotency marker, and event commit in one
   transaction.
3. Cancellation changes a confirmed reservation and restores capacity in one
   transaction.
4. Validation changes only a confirmed reservation and writes one validation
   record in one transaction.
5. A foreign tenant partition cannot return the reservation even if its ID or
   validation code is known.

## Known limitations

The prototype has no TTL attribute or archival flow, so the production
retention requirement is not yet implemented. Tenant metrics currently query
and aggregate reservation items; at large scale they should use asynchronous
materialized counters rather than reading an unbounded partition.

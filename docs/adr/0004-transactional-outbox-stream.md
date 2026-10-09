# ADR 0004 Derive asynchronous events from DynamoDB Streams

## Status

Accepted for event forwarding; downstream consumer remains open.

## Context

Reservation and validation actions need audit or notification events. Writing
the database and SQS independently from the API creates a dual-write failure:
the reservation can commit while the message fails, or the message can be sent
for a transaction that later fails.

## Decision

Write an event item in the same DynamoDB transaction as the business change.
Enable DynamoDB Streams and invoke a Lambda function that forwards only event
items to a FIFO SQS queue. Use tenant ID as the message group and event sort key
as the deduplication ID.

## Alternatives rejected

- **Direct SQS send after database commit:** simple but loses events when the
  process fails between the two operations.
- **Synchronous notification inside the request:** increases user latency and
  couples reservation availability to a non-critical consumer.
- **Periodic table scan:** delays delivery and wastes reads.

## Consequences

The event is atomic with reservation state and consumers can be unavailable
without blocking users. Streams and SQS are at-least-once systems, so downstream
processing still must be idempotent. FIFO ordering applies within a tenant, not
globally. The current repository stops at the queue; experiment E6 cannot claim
end-to-end recovery until an idempotent consumer and observable processed-event
record are implemented.

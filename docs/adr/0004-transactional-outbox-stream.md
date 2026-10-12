# ADR 0004 Derive asynchronous events from DynamoDB Streams

## Status

Accepted for event forwarding. The Alibaba Cloud SQL deployment now includes a
database-backed idempotent audit consumer for E6; the AWS queue consumer remains
open.

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
globally. For the Alibaba Cloud MySQL deployment, `audit_events` acts as the
transactional outbox and `processed_events` is the idempotent downstream audit
store. Tenant-scoped controls expose pause, resume, queue depth, oldest-message
age, and processed totals for E6. The AWS deployment still stops at the SQS
queue and requires its own downstream consumer before the same claim can be
made there.

# ADR 0002 Use DynamoDB for reservation state

## Status

Accepted.

## Context

The critical operation is reserving the final available places without
overselling while supporting safe client retries. Access patterns are scoped to
one tenant and known identifiers; the prototype does not need joins, reporting
queries, or free-form search. The student team should not operate database
patching, replication, or failover.

## Decision

Use a DynamoDB on-demand table with conditional transactional writes, point-in-
time recovery, encryption, a validation-code GSI, and Streams. Store capacity,
reservation, idempotency marker, and event in one transaction.

## Alternatives rejected

- **PostgreSQL on a virtual machine:** familiar transactions and SQL, but the
  team would own failover, patching, backups, and connection capacity.
- **Managed PostgreSQL:** operationally stronger, but connection-pool behaviour
  and fixed instance cost add variables that are not required by the access
  patterns.
- **Document database without multi-item transactions:** simpler documents but
  weaker evidence for atomic capacity and idempotency.

## Consequences

Conditional transactions provide an explicit overselling invariant and
on-demand capacity removes provisioned-throughput planning at launch. The model
must be designed around access patterns, and pooled tenant data makes a missing
partition key dangerous. Aggregate metrics become expensive if implemented as
unbounded partition queries. DynamoDB Local and Moto improve development speed
but cannot prove service latency, throttling, durability, or recovery in AWS.

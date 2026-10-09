# ADR 0006 Scale ECS tasks from ALB request count

## Status

Accepted as the first policy to evaluate.

## Context

Holiday slot releases can create short request bursts. CPU is not necessarily a
good leading signal because an API task may wait on DynamoDB while its request
queue grows. A useful policy must be simple enough to explain and must expose a
measurable reaction delay.

## Decision

Use ECS target tracking on ALB request count per target, with a minimum of two
tasks, maximum of six, and a configurable target. Measure the time from a demand
step until task count increases and p95 remains below 500 ms for three
consecutive one-second intervals.

## Alternatives rejected

- **CPU target tracking:** portable but may react after latency rises and may
  not reflect I/O-bound saturation.
- **Queue-depth scaling:** appropriate for asynchronous workers but the critical
  reservation request is synchronous and does not pass through SQS.
- **Scheduled scaling:** useful for known releases but cannot protect against an
  unexpected burst by itself.
- **Predictive or learned scaling:** needs workload history unavailable to a new
  three-tenant platform.

## Consequences

The policy is transparent and uses a metric already produced by the ALB. It may
still react too slowly because metric aggregation, task launch, image pull, and
health checks occur after demand arrives. A configured policy is not evidence
of elasticity. If the spike experiment misses the target, the next comparison
should test scheduled pre-scaling or a more aggressive target, including the
additional idle cost.

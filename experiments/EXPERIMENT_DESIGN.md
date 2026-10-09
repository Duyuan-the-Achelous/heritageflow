# HeritageFlow Experiment Design

## Scope and evidence rules

All experiments must run against the deployed cloud environment. Local runs are
engineering checks only and must not be reported as cloud-performance evidence.
Preserve raw k6 JSON or CSV output, cloud metrics, deployment revision, IaC
commit, service configuration, instance count, region, and UTC timestamps.

## E1 Baseline load and degradation point

Question: At what offered demand does the reservation API stop meeting its
latency and error targets?

- Independent variable: 1, 10, 25, 50, and 100 concurrent virtual users.
- Controlled variables: one region, one ticket slot, one-seat requests, fixed
  payload, same client location, same build and scaling policy.
- Measures: p50, p95, p99, requests/s, application errors, connection errors,
  CPU, memory, task count, database latency/throttling, and queue depth.
- Replication: one warm-up run, then at least three measured runs per level.
- Initial target: p95 below 500 ms, p99 below 1 s, unexpected error rate below
  1%. Capacity-exhausted responses are business rejections, not platform errors.
- Output: `results/e1-load-<timestamp>.json` plus a summary CSV generated from
  the raw output.

Use `experiments/k6/load.js`. Create a slot whose capacity exceeds the total
planned requests so E1 measures infrastructure rather than business capacity.

## E2 Release-time demand spike and scaling delay

Question: How long does the platform take to recover its latency target after a
step from 5 to 100 virtual users?

- Measure task-count changes and p95 latency in 1-second intervals.
- Define scaling delay as the time from the demand step until p95 remains below
  500 ms for three consecutive intervals.
- Record user-visible errors and the maximum p99 during the recovery window.
- Run at least three repetitions after returning the service to its baseline
  task count.

Use `experiments/k6/spike.js` and export the container-service scaling events.

## E3 Concurrent capacity safety

Question: Can concurrent reservation requests oversell the final seats?

- Configure a new slot with capacity 20.
- Send 100 unique, simultaneous one-seat reservation requests.
- Expected invariant: exactly 20 confirmed seats, 80 capacity rejections,
  remaining capacity 0, and no negative capacity.
- Repeat with retries that reuse the same idempotency keys.
- Expected invariant after retries: reservation count and consumed capacity are
  unchanged.

The automated unit test exercises this invariant locally. The cloud run must
repeat it against the production storage implementation.

## E4 Tenant isolation

Question: Can one attraction access or validate another tenant's reservation?

For each tenant pair, test list, read, cancel, validation, and a tampered
tenant-id payload. Expected outcomes are 401 without authentication, 403 for a
known but forbidden operation, or 404 when hiding another tenant's resource.
No response may disclose the foreign reservation body or validation code.

Run the matrix in CI on every deployment. Save the JUnit output.

## E5 Instance failure and recovery

Question: What does a visitor experience when one API instance disappears under
steady load?

- Establish steady load with at least two healthy API tasks.
- Terminate one task without first draining it.
- Measure failed requests, p95/p99 change, load-balancer detection time,
  replacement start time, and time to restored task count.
- Define recovery time from termination to stable target latency and healthy
  task count.
- Run three repetitions.

Do not inject failure into the database until backups and a recovery procedure
have been tested separately.

## E6 Async consumer outage

Question: Are reservation events preserved while the audit or notification
consumer is unavailable?

- Disable the consumer while sending a fixed reservation workload.
- Measure queue depth and oldest-message age.
- Restore the consumer and measure drain time.
- Verify that every event is processed once logically; duplicate delivery is
  acceptable only when the consumer is idempotent.

## E7 Cost and unit economics

Collect the measured monthly fixed cost and request-dependent prices. Report:

- cost per tenant per month;
- cost per 1,000 reservation requests;
- fixed versus variable percentage;
- launch, 10x, and 100x demand scenarios;
- the scale at which the chosen compute or database model becomes uneconomic;
- excluded prices and uncertainty ranges.

Do not count free-tier discounts in the primary model. They may be shown as a
separate student-budget scenario.


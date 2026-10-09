# Non-functional requirements

These targets are fixed before public-cloud evaluation. Local measurements are
engineering baselines and cannot be used as proof of cloud performance.

| ID | Dimension | Measurable target | How it will be measured |
|---|---|---|---|
| NFR-01 | Availability | 99.5% monthly availability for the reservation API. Downtime is any five-minute interval in which more than 1% of valid reservation requests fail unexpectedly. | ALB request counts and 5xx alarms, supplemented by an external probe. |
| NFR-02 | Latency | Reservation creation p50 < 150 ms, p95 < 500 ms, and p99 < 1,000 ms while the unexpected-error rate remains < 1%. Capacity rejections are business outcomes, not platform errors. | k6 client-side distributions at five demand levels, three measured repetitions per level. |
| NFR-03 | Scale | Launch: 3 tenants, 100 simultaneous users, and 10 requests/s. Evaluation ceiling: 100 tenants and 1,000 requests/s or the observed degradation point, whichever comes first. | Load levels, ALB throughput, ECS task count, CPU, memory, and DynamoDB throttling. |
| NFR-04 | Tenancy | Pooled application and table with tenant ID derived from authentication. Every cross-tenant read, cancel, and validation attempt returns 403 or 404 and discloses no foreign body or code. | Pairwise isolation matrix in CI and after deployment. |
| NFR-05 | Capacity integrity | Concurrent requests never produce negative capacity or confirmed seats above the configured slot capacity. Reusing an idempotency key never consumes capacity twice. | 100 simultaneous one-seat requests against a 20-seat slot, followed by idempotent retries. |
| NFR-06 | Durability | RPO <= 5 minutes and RTO <= 30 minutes for reservation data. | DynamoDB point-in-time recovery configuration review and a documented restore drill before database fault injection. |
| NFR-07 | Recovery | Loss of one API task causes < 1% unexpected errors and returns to the desired healthy task count and p95 target within 120 seconds. | Three task-termination experiments under steady load. |
| NFR-08 | Compliance | Assessment data is synthetic and remains in one declared AWS region. A production China deployment requires PIPL review, an approved China-region provider, a retention schedule, and deletion controls before real visitor data is used. | Configuration evidence and a limitations statement; no claim of production compliance in this prototype. |
| NFR-09 | Cost | At launch, cloud cost < USD 25 per tenant/month and < USD 0.10 per 1,000 reservation requests, excluding support and taxes. Report fixed/variable split and 10x/100x projections. | Public price inputs plus measured request, storage, metric, and task usage. Free tiers are excluded from the primary model. |
| NFR-10 | Security | HTTPS at the public boundary; opaque tenant-scoped tokens from Secrets Manager; no repository secrets; API tasks accept traffic only from the ALB; visitor references are HMAC-hashed. | Terraform review, secret scan, runtime configuration, and negative authentication tests. |
| NFR-11 | Observability | Every request has a request ID, route, status, duration, and tenant ID when authenticated. Alerts cover API 5xx and oldest queue-message age. | JSON log inspection, response-header test, and CloudWatch alarm evidence. |
| NFR-12 | Reproducibility | A third party can build the local system with one Compose command and associate every measured result with a Git commit and runtime configuration. | Clean-start rehearsal, README review, and metadata stored beside raw results. |

## Evaluation rules

- Report distributions rather than averages.
- Preserve raw output and the script used to produce every figure.
- Record image digest, commit, region, task definition, task count, and UTC time.
- Report missed targets and excluded costs explicitly.

# Requirement and evidence traceability

| Requirement | Implementation | Local evidence | Cloud evidence | Status |
|---|---|---|---|---|
| NFR-01 availability | Two-task ECS service, ALB health checks, 5xx alarm. | Process health only. | External probe and monthly ALB metrics. | Cloud evidence required. |
| NFR-02 latency | Stateless FastAPI, DynamoDB transactions. | k6 scripts exist; no recorded run. | Five levels, three repetitions, latency distributions. | Open. |
| NFR-03 scale | ECS target tracking 2–6 tasks; DynamoDB on demand. | Not reproducible locally. | Task-count and degradation-point experiment. | Cloud evidence required. |
| NFR-04 tenancy | Auth-derived tenant partition on every access path. | Unit and DynamoDB Local isolation tests pass. | Full pairwise matrix after deployment. | Partially evidenced. |
| NFR-05 capacity | Conditional decrement in a DynamoDB transaction. | Unit oversell test passes. | 100-way production-path experiment. | Partially evidenced. |
| NFR-06 durability | DynamoDB PITR enabled in Terraform. | Configuration only. | Restore drill and measured RPO/RTO. | Open. |
| NFR-07 recovery | Multiple ECS tasks and ALB replacement. | Not reproducible locally. | Three task-termination runs. | Cloud evidence required. |
| NFR-08 compliance | Synthetic data and declared region. | Repository contains no real visitor dataset. | Region and retention evidence. | Design only. |
| NFR-09 cost | Budget alarm and low-fixed-cost public-subnet design. | Terraform variables only. | Cost model using measured usage and public prices. | Open. |
| NFR-10 security | Secret injection, SG boundary, HMAC, role checks. | Secret scan and negative API tests pass. | HTTPS and IAM evidence. | Partially evidenced. |
| NFR-11 observability | CloudWatch logs and two alarms. | Basic Uvicorn logs. | Structured logs, request IDs, alarm test. | In progress. |
| NFR-12 reproducibility | Compose, Terraform, README, Git tag. | Clean Compose start and integration test pass. | Pipeline deployment from an empty environment. | Partially evidenced. |

## Course deliverables

| Deliverable | Repository evidence | Remaining work |
|---|---|---|
| Application code | `src/heritageflow` | Continue only where an experiment requires it. |
| Infrastructure as code | `infra/terraform` | Provider validation and real apply. |
| CI/CD | `.github/workflows/ci.yml` | Build, integration test, Terraform validation, deploy. |
| Load-test scripts | `experiments/k6` | Capacity, isolation, failure, consumer, and cost scripts. |
| Raw load and cost data | `results` | No measured files yet. |
| IEEE paper | None | 8–10 page English paper after evidence collection. |
| Presentation | None | 8-minute technical and 4-minute stakeholder versions. |

# Alibaba Cloud implementation roadmap

## Scope decision

The existing Lightweight Application Server deployment is a public preview and
fallback demonstration environment. It proves the user journey, container
packaging, HTTPS termination, persistence, tenant-aware authorization, capacity
integrity, and single-use admission validation. It is not the final evaluation
platform because one manually operated server cannot demonstrate horizontal
scaling or managed data resilience.

The target evaluation environment keeps the application thin and moves platform
responsibilities to managed Alibaba Cloud services:

- Alibaba Cloud Container Registry stores immutable application images.
- Serverless App Engine runs two or more container instances and scales them in
  response to measured demand.
- ApsaraDB RDS MySQL stores shared, tenant-scoped platform state and provides
  managed backups.
- GitHub Actions builds, tests, scans, publishes, and deploys each revision.
- Simple Log Service and CloudMonitor collect evidence after the core platform
  is working; they are deliberately deferred to avoid premature monitoring cost.

The editable target diagram is `diagrams/alicloud-architecture.mmd`.

## Build order

### Phase A Current preview baseline complete

- Docker image v3 is reachable through Nginx and HTTPS.
- The container binds only to localhost; ports 80 and 443 form the public edge.
- SQLite data is stored in a named volume and backed up before destructive tests.
- The IP certificate renews automatically through a systemd timer.

### Phase B Application portability complete locally

1. Introduce a database interface that supports SQLite for local development and
   MySQL for the managed environment.
2. Preserve the same reservation invariants in MySQL transactions: capacity
   cannot become negative, idempotency keys are unique, and one visitor cannot
   hold duplicate active reservations for one slot.
3. Add MySQL integration tests in Docker Compose.
4. Build image v4 and verify that no state is written inside the container.

Exit criterion: two application containers can share one database and return
consistent capacity and reservation results.

Verified on 2026-10-10 with MySQL 8.4 and two API containers. The integration
test confirmed cross-instance visibility, idempotent replay, shared capacity,
and database-enforced prevention of concurrent duplicate active bookings. No
RDS or other paid Alibaba Cloud resource was created for this verification.

### Phase C Managed cloud skeleton

1. Create an Alibaba Cloud Container Registry repository.
2. Provision VPC networking, RDS MySQL, and Serverless App Engine with Terraform.
3. Keep database endpoints private and expose only the HTTPS application entry.
4. Store runtime tokens and database credentials outside the repository.

Exit criterion: destroying and reapplying Terraform recreates the environment,
and the application is reachable without manual container installation.

### Phase D Automation

1. Run tests and secret scanning in GitHub Actions.
2. Build a commit-addressed image and push it to Container Registry.
3. Deploy the image revision to Serverless App Engine.
4. Record the commit, image digest, deployment revision, region, and UTC time.

Exit criterion: a source commit reaches the cloud through the pipeline without
SSH deployment commands.

### Phase E Evidence and operations

1. Enable logs, metrics, an availability probe, and at least one alert.
2. Execute five load levels and measure p50, p95, p99, throughput, and errors.
3. Measure scaling delay during a step load increase.
4. terminate one application instance under load and measure recovery.
5. Produce measured cost per tenant and per 1,000 requests.

Exit criterion: raw measurements and configuration metadata are saved under
`results/` and every reported number is reproducible.

## Cost guardrail

Do not enable paid monitoring, RDS, or Serverless App Engine resources until the
relevant phase is ready to use them. Review the console estimate, set a budget,
tag every resource with the project name, and destroy evaluation resources after
the assessment window. Free credits may be reported separately but must not be
used as the primary cost model.

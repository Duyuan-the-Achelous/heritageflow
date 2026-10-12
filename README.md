# HeritageFlow

HeritageFlow is a course-project prototype for a multi-tenant reservation and
admission-control platform. The seeded tenant profiles represent Luoyang
Guanlin, Luoyang Ancient Tomb Museum, and Wan'an Mountain. They are independent
case-study tenants; this repository does not claim that they share a real
operator or production system.

## Current vertical slice

- tenant-scoped authentication;
- three heterogeneous attraction profiles;
- configurable capacity slots;
- atomic capacity decrement;
- idempotent reservation creation;
- authenticated, tenant-scoped reservation listing;
- cancellation with capacity restoration;
- single-use, tenant-scoped admission validation;
- privacy-preserving visitor-reference hashing;
- audit records and tenant-level counters;
- tests for isolation, idempotency, validation, cancellation, and overselling;
- k6 baseline-load and spike experiments.
- selectable SQLite and DynamoDB storage backends;
- MySQL shared storage for horizontally scaled Alibaba Cloud deployments;
- DynamoDB transactional capacity, idempotency, and audit-event writes;
- DynamoDB Streams to FIFO SQS event forwarding;
- Terraform for AWS VPC, ECS Fargate, ALB, DynamoDB, SQS, monitoring, secrets,
  budget alerts, and autoscaling.

Real payments, government identity verification, OTA integrations, physical
gates, and face recognition are deliberately outside the prototype.

## Run locally with SQLite

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:HERITAGEFLOW_ENV = "development"
$env:HERITAGEFLOW_DB_PATH = ".\heritageflow.db"
.\.venv\Scripts\python.exe -m uvicorn heritageflow.main:app --reload
```

Open `http://localhost:8000/docs`. Development tokens use this format:

```text
demo:<tenant-id>:<role>
```

Examples:

```text
demo:guanlin:tenant_admin
demo:tomb-museum:visitor
demo:wanan-mountain:validator
```

Demo-token parsing is disabled when `HERITAGEFLOW_ENV` is not `development`.
Production deployments must inject opaque token mappings and the visitor HMAC
key through the runtime environment or secret manager.

## Verify

```powershell
.\.venv\Scripts\python.exe scripts\check_secrets.py
.\.venv\Scripts\python.exe -m pytest
```

Raw, sanitized experiment JSON and CSV files belong in `results/` and are kept
in version control so every paper figure can be reproduced. Put disposable
local output under `results/.local/`.

The experiment protocol is in `experiments/EXPERIMENT_DESIGN.md`. Performance
claims must come from the deployed cloud service, not the local SQLite baseline.

## Run the production data path locally

Docker Compose runs the API against persistent DynamoDB Local data, creates the
same keys and GSI used by Terraform, and seeds the three demonstration tenants.

```powershell
docker-compose up --build
```

Open `http://localhost:8000/` for the visitor, attraction-management, and
admission-validation web interface. API documentation is available at
`http://localhost:8000/docs`. Process liveness is available at `/health`;
dependency readiness is available at `/ready`. Every response includes an
`X-Request-ID`, and request completion is written as JSON without tokens,
visitor references, or validation codes. DynamoDB Local is exposed separately
on host port `8001`. Stop the services without deleting data with `docker-compose down`;
add `--volumes` only when you intentionally want a clean local database.

Run the end-to-end test against DynamoDB Local with:

```powershell
docker-compose --profile test run --rm integration-tests
```

With the API running, execute the guided demonstration and three local
engineering-baseline experiments:

```powershell
.\scripts\demo.ps1
.\.venv\Scripts\python.exe experiments\capacity_safety.py
.\.venv\Scripts\python.exe experiments\tenant_isolation.py
.\.venv\Scripts\python.exe experiments\idempotency_retry.py
.\.venv\Scripts\python.exe experiments\summarize_results.py `
  results\.local\capacity-safety-*.json `
  results\.local\tenant-isolation-*.json `
  results\.local\idempotency-retry-*.json `
  --output results\.local\summary.csv
```

Each experiment exits non-zero when its invariant fails and records the Git
commit, UTC timestamp, parameters, metrics, and pass/fail result. These runs are
local correctness evidence, not cloud performance claims.

The test creates and deletes its own table. It verifies seeding, API-level
idempotency, cross-tenant isolation, persistence across an application restart,
and single-use admission validation.

## Verify the Alibaba Cloud data path locally

This Compose stack runs two independent API containers against one MySQL 8.4
database. It verifies that capacity, idempotency, and duplicate-booking rules
remain consistent across application instances before an RDS instance is
created.

```powershell
docker compose -f compose.mysql.yaml --profile test up --build `
  --abort-on-container-exit --exit-code-from integration-tests
docker compose -f compose.mysql.yaml down
```

During manual testing, API A is available at `http://localhost:8010` and API B
at `http://localhost:8012`. Both display the same data. Add `--volumes` to the
`down` command only when you intentionally want to erase the local MySQL data.

The managed deployment uses the same image with `HERITAGEFLOW_STORAGE=mysql`
and supplies `HERITAGEFLOW_MYSQL_HOST`, `HERITAGEFLOW_MYSQL_PORT`,
`HERITAGEFLOW_MYSQL_DATABASE`, `HERITAGEFLOW_MYSQL_USER`, and
`HERITAGEFLOW_MYSQL_PASSWORD` from the cloud runtime configuration.

## Single-server cloud preview

The preview Compose file is for the first public smoke test on a small Linux
server. It runs one API container with a persistent SQLite volume and does not
represent the final scalable architecture.

```bash
python3 scripts/generate_preview_env.py
sudo docker compose --env-file .env.preview -f compose.preview.yaml up --build -d
sudo docker compose --env-file .env.preview -f compose.preview.yaml ps
```

Keep `.env.preview` on the server only. Do not commit it or paste its contents
into an issue, report, or chat. The final cloud evaluation must use a managed
shared database and horizontally scalable compute instead of this preview.

## Alibaba Cloud pipeline deployment

GitHub Actions can update the existing SAE image after tests and ACR
publication. This deployment job is disabled until repository variable
`SAE_DEPLOY_ENABLED` is explicitly set to `true`. It uses a dedicated RAM
credential, a commit-tagged image, a rolling-release policy, change-order
polling, and public health/readiness probes. Review permissions and release
policy in [the SAE pipeline guide](docs/sae-pipeline-deployment.md) before
enabling it. Local implementation does not establish a successful cloud run.
The Alibaba Cloud Terraform environment is not yet fully defined or rebuildable.

## AWS deployment

The cloud backend is selected with:

```text
HERITAGEFLOW_STORAGE=dynamodb
HERITAGEFLOW_DYNAMODB_TABLE=heritageflow
HERITAGEFLOW_AWS_REGION=eu-west-1
```

AWS resources and deployment instructions are in
`infra/terraform/README.md`. The cloud path stores reservation capacity,
idempotency markers, reservations, and audit events in one DynamoDB transaction.
Event items are forwarded from DynamoDB Streams to a FIFO SQS queue, avoiding a
database/SQS dual write in the API process.

## Known boundary

SQLite serializes the capacity transaction and is used only to prove the API
invariants locally. The cloud implementation will replace it with a managed
store that supports conditional writes. The DynamoDB implementation is covered
by mocked-AWS transaction tests, but Terraform must still be validated and
applied against the student's AWS account before deployment evidence is used in
the paper.

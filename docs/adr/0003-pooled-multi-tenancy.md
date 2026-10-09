# ADR 0003 Use pooled multi-tenancy with tenant-key enforcement

## Status

Accepted.

## Context

The case-study customer sells one platform to small attractions. A separate
deployment or database for each launch tenant would provide strong isolation
but would duplicate infrastructure, deployment, alarms, and fixed costs. The
primary threat is a legitimate tenant attempting to access another tenant's
records.

## Decision

Use one application deployment and one DynamoDB table. Authentication maps an
opaque token to a server-side tenant ID and role. Every tenant-owned item uses a
partition key derived from that principal. Cross-tenant records are hidden with
404 where revealing existence is unnecessary. Run pairwise isolation tests as
a deployment gate.

## Alternatives rejected

- **Silo per tenant:** strongest blast-radius boundary but disproportionate
  fixed cost and operational duplication for small tenants.
- **Schema per tenant in a relational database:** easier SQL isolation than a
  pooled schema but still creates migrations and connection-management work per
  tenant.
- **Client-supplied tenant identifier:** simple routing but allows tampering and
  is not an acceptable trust boundary.

## Consequences

Pooling supports the SaaS cost model and one deployment pipeline. A missing
tenant key in any new access path can become a high-impact data leak, so code
review alone is insufficient. Isolation tests must cover list, get, cancel,
validation, admin routes, missing authentication, and tampered payloads. This
decision isolates data logically rather than with separate AWS accounts or
tables; the paper must describe that tradeoff honestly.

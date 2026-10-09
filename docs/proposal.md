# HeritageFlow platform proposal

## Industry and named customer

HeritageFlow is a multi-tenant reservation and admission-control platform for
small and medium cultural-heritage attractions. Its named customer is Luoyang
Heritage Cloud Ltd., a fictional case-study SaaS operator that sells one shared
platform to independently managed attractions. The first pilot profiles are
Guanlin, the Luoyang Ancient Tomb Museum, and Wan'an Mountain. They deliberately
have different admission rules and remain separate tenants.

The primary user is the operator's platform manager. Tenant administrators
publish capacity-controlled time slots and view their own counters; visitors
reserve places; gate staff validate a single-use code. The critical journey is
creating a reservation without overselling the final places. The critical
security property is that one attraction must never read, cancel, or validate
another attraction's reservation.

## Problem

Independent attractions can buy ticketing software, but a small SaaS operator
needs capabilities that are platform-wide rather than attraction-specific:
tenant isolation, burst absorption when slots are released, auditable capacity
transactions, consistent deployments, per-tenant operational evidence, and a
shared cost base. Building a separate application and database for every site
duplicates operational work and makes small tenants uneconomic.

HeritageFlow therefore implements only the thin vertical slice needed to test
those platform properties. Payments, identity verification, physical gates,
face recognition, and OTA integrations are outside the prototype.

## Why cloud

The unavoidable force is **multi-tenancy**. One codebase and operating team must
serve many independently administered attractions while every request and data
item remains tenant-scoped. Three unrelated single-machine installations would
avoid the isolation problem but would also remove the shared platform business
model, central deployment pipeline, pooled capacity, and per-tenant unit
economics that the customer is buying.

Elasticity is the second force to test. Normal reservation demand can be low,
but a newly released holiday slot can produce a short step increase. The cloud
design maintains two baseline API tasks and scales horizontally from load. A
managed conditional-write database protects capacity while tasks are added or
replaced. The evaluation will measure whether scaling reacts quickly enough;
autoscaling is not treated as successful merely because it is configured.

## Proposed contribution

HeritageFlow tests whether a pooled, transaction-safe reservation platform can
give small attractions demonstrable tenant isolation and burst-safe capacity at
a defensible per-tenant cost. Its intended contribution is evidence: isolation
tests, concurrency invariants, scaling delay, failure recovery, and unit cost,
including targets that the deployment misses.

# ADR 0005 Use one region across multiple availability zones

## Status

Accepted for the assessment deployment.

## Context

The platform needs resilience to one API task or availability-zone failure but
has a limited student budget. Active-active multi-region operation would add
replication, routing, consistency, data-residency, and testing complexity. The
target availability is 99.5%, not continuous operation through a regional
outage.

## Decision

Deploy one VPC in one declared AWS region with two subnets in distinct
availability zones. Run at least two ECS tasks behind a regional ALB and use
DynamoDB's managed regional service. Keep assessment data synthetic.

## Alternatives rejected

- **Single task and single subnet:** cheapest, but provides no meaningful task
  or zone failure experiment.
- **Active-passive second region:** improves disaster recovery but requires data
  replication, DNS failover, duplicate infrastructure, and a second cost base.
- **Active-active multi-region:** best regional availability but creates
  conflict resolution and consistency questions larger than the project.

## Consequences

The design can test task replacement and multi-AZ scheduling at moderate cost.
A complete region outage remains an accepted risk. The current default
`eu-west-1` is suitable only for synthetic assessment data; a real Luoyang
deployment would require an approved China-region hosting and compliance
decision. RPO and RTO claims still require a restore procedure and experiment.

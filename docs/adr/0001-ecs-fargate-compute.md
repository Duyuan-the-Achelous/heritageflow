# ADR 0001 Use ECS Fargate for the synchronous API

## Status

Accepted for the assessment architecture.

## Context

The API is a conventional HTTP service with several related routes, shared
startup configuration, and a Python dependency set. The experiment must observe
horizontal task count, replacement after failure, and user-visible behaviour
during scaling. Expected launch traffic is low, but the course requires a
scaling mechanism and deliberate instance failure.

## Decision

Run the FastAPI container as an ECS Fargate service behind an Application Load
Balancer, with two baseline tasks and target-tracking scaling up to six tasks.
Use the same image locally and in the cloud.

## Alternatives rejected

- **Lambda plus API Gateway:** lower idle cost and automatic scaling, but it
  changes the failure and scaling experiment to function cold starts and removes
  an observable long-running instance lifecycle.
- **EC2 virtual machines:** gives operating-system control but adds patching,
  capacity management, and host configuration outside the project's question.
- **Kubernetes:** supports rich scheduling but introduces a control-plane and
  operational surface unjustified by one service.

## Consequences

Fargate makes container replacement and task-count scaling directly measurable
and avoids host administration. The ALB and two always-on tasks create a fixed
monthly cost that may dominate at three tenants. Scale-to-zero is unavailable,
and task startup may be slower than a warm process. The cost experiment must
identify when Lambda or fewer reserved tasks would become more economical.

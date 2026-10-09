# Threat model

## Scope and assets

The primary threat is a legitimate tenant attempting to access another
tenant's reservation data through a guessed identifier, validation code,
tampered payload, or missing server-side filter. Protected assets are remaining
capacity, reservation state, validation codes, hashed visitor references,
tenant configuration, API credentials, and audit events.

The model covers the public API, ALB-to-task boundary, ECS task identity,
DynamoDB table, Secrets Manager, event Lambda, and SQS. Payment data, government
identity documents, face images, and physical gate devices are outside scope.

## Trust boundaries

1. Internet client to public load balancer.
2. Load balancer to ECS task security group.
3. Application task to AWS managed services under IAM.
4. DynamoDB Stream to Lambda and Lambda to SQS.
5. CI/CD identity to ECR, Terraform, and ECS deployment.

## Threats and controls

| Threat | Example | Current control | Remaining work |
|---|---|---|---|
| Spoofing | Reusing or guessing a tenant token. | Opaque token mapping outside development; role validation. | Define rotation and revocation; replace static tokens for production. |
| Tenant-data disclosure | Tenant B requests Tenant A's reservation ID. | Tenant-derived partition key; foreign records return 404; pairwise tests. | Run full matrix in CI and cloud. |
| Payload tampering | Client supplies another `tenant_id`. | Tenant comes from authenticated principal; body tenant fields are ignored. | Reject unknown fields explicitly for clearer evidence. |
| Capacity tampering | Concurrent requests oversell a slot. | DynamoDB conditional transaction. | Execute 100-way cloud concurrency experiment. |
| Replay | Client retries a successful reservation. | Tenant-scoped hashed idempotency marker. | Define retention/expiry for idempotency markers. |
| Validation replay | Same code is presented twice. | Conditional status transition; second use returns conflict. | Rate-limit repeated invalid attempts. |
| Secret disclosure | Credentials committed or logged. | `.gitignore`, high-confidence secret scan, Secrets Manager design. | Add managed secret scanner and review CI log redaction. |
| Network interception | HTTP public listener. | Optional ACM/HTTPS Terraform path. | HTTPS certificate is mandatory before assessment exposure. |
| Privilege escalation | Visitor calls an admin route. | Route-level role checks. | Add a complete role/route authorization matrix. |
| Denial of service | Slot release causes a burst. | ALB, baseline tasks, autoscaling, on-demand DynamoDB. | Rate limits and measured scaling delay. |
| Repudiation | Operator disputes cancellation or validation. | Immutable event items and stream forwarding. | Implement idempotent consumer and retention policy. |
| Supply-chain compromise | Modified dependency or workflow action. | Version ranges and Git history. | Pin workflow actions by commit and add dependency scanning. |

## Privacy position

Visitor references are HMAC-hashed before storage. The prototype uses synthetic
data only. A hash does not make real visitor data automatically compliant; a
production deployment still needs purpose limitation, retention, deletion,
access control, breach response, and applicable PIPL/GDPR review.

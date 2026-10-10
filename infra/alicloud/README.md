# Alibaba Cloud infrastructure

This directory is the Terraform entry point for the Alibaba Cloud evaluation
environment described in `docs/alicloud-roadmap.md`. The initial commit pins the
provider, region, naming, and cost-allocation tags without creating billable
resources. Resource files will be added phase by phase only after the application
supports a shared MySQL database.

## Planned resource groups

- `network.tf`: VPC, vSwitches, and security boundaries.
- `registry.tf`: Container Registry repository.
- `database.tf`: private ApsaraDB RDS MySQL instance, database, and account.
- `compute.tf`: Serverless App Engine application and scaling policy.
- `observability.tf`: logs, metrics, alerts, and budget controls after deployment.

## Authentication

Use a least-privilege RAM identity through environment variables or an approved
CI secret store. Never put access keys, database passwords, tenant tokens, or
Terraform state in this directory.

## Safe initial validation

The current scaffold creates no cloud resources, so these commands are safe once
Terraform is installed:

```powershell
terraform init
terraform fmt -check
terraform validate
```

Do not run `terraform apply` until a later phase includes reviewed resources and
the Alibaba Cloud console shows the expected monthly cost.


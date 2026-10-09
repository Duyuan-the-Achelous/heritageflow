# AWS deployment

This Terraform stack creates the assessment environment rather than relying on
an existing VPC. It provisions two public subnets, an ALB, ECS Fargate tasks,
DynamoDB, DynamoDB Streams, a stream-forwarding Lambda, FIFO SQS with a dead
letter queue, CloudWatch alarms, SNS email alerts, Secrets Manager, ECR, and an
AWS Budget.

The Fargate tasks use public IPs to avoid the fixed cost of a NAT gateway in a
student project. The security group accepts application traffic only from the
ALB. Record this cost/security trade-off in DR-5.

## Prerequisites

- AWS CLI authenticated to the intended student account.
- Terraform 1.8 or later.
- Docker Desktop running.
- An email address that can confirm the SNS subscription.

Never commit a real `terraform.tfvars` file. It contains runtime authentication
tokens. The repository ignores `*.tfvars` and Terraform state.

## Bootstrap ECR and push the first image

Copy `terraform.tfvars.example` to `terraform.tfvars` and replace every example
value. Then create only the repository:

```powershell
terraform init
terraform apply -target=aws_ecr_repository.app
$repo = terraform output -raw ecr_repository_url
$account = aws sts get-caller-identity --query Account --output text
aws ecr get-login-password --region eu-west-1 |
  docker login --username AWS --password-stdin "$account.dkr.ecr.eu-west-1.amazonaws.com"
docker build -t heritageflow ..\..
docker tag heritageflow:latest "${repo}:v0.1.0"
docker push "${repo}:v0.1.0"
```

Set `container_image` in `terraform.tfvars` to the pushed URI and apply the full
stack:

```powershell
terraform plan -out plan.tfplan
terraform apply plan.tfplan
terraform output -raw api_url
```

Confirm the SNS subscription email before relying on alarms.

## Seed the three demonstration tenants

The production service does not create demo tenants automatically. Run one
temporary task with `HERITAGEFLOW_SEED_DEMO=true`, or seed through an approved
administrative migration. Do not leave automatic seeding enabled in the steady
state service.

## Experiment evidence

Before each measured run, save `terraform output`, the ECS task-definition ARN,
service desired/running count, image digest, scaling policy, AWS region, and UTC
timestamps. Destroy the stack after the assessment window:

```powershell
terraform destroy
```

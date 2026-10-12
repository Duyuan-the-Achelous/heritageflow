# Deploy the existing SAE application from GitHub Actions

## Scope and current status

The workflow now includes an opt-in `deploy-sae` job after tests and ACR image
publication. It updates an existing image-based application, waits for its SAE
change order, checks the configured image, and requires three consecutive
successful public `/health` and `/ready` probe pairs. It does not create a
database, application, load balancer, or other cloud resource.

This is implementation, not evidence of a completed cloud deployment. RAM and
GitHub configuration and a successful real run are still required. The Alibaba
Cloud Terraform scaffold remains a separate, unfinished deliverable.

Default non-secret target settings:

| Setting | Value |
|---|---|
| Region | `cn-beijing` |
| Application | `heritageflow` |
| Application ID | `1187c616-c49b-4b0f-8cec-2f9e45989acd` |
| Public origin | `http://182.92.2.36` |
| Image tag | Full Git commit SHA from the same workflow run |

HTTP probes do not establish HTTPS or transport security. Use only synthetic
assessment data. The deployment runner does not send tenant tokens or database
credentials to the public origin.

## Prepare a dedicated RAM identity

Use a dedicated deployment identity, not the account owner's AccessKey. For the
three SDK calls in this runner, create a custom policy with these actions:

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sae:DescribeApplicationConfig",
        "sae:DeployApplication",
        "sae:DescribeChangeOrder"
      ],
      "Resource": "*"
    }
  ]
}
```

The official API authorization tables specify `Resource: "*"` for these calls.
This policy restricts actions but is **not application-scoped**: its deployment
action can affect other SAE applications accessible to that identity. The
runner's AppId check is a safety check, not an IAM boundary. Do not describe
this as permission limited to a single application. Review any additional
SAE permission-assistant restrictions supported by the account before use.
Do not grant `AdministratorAccess`, blanket `sae:*`, RDS mutation permissions,
or permission to create resources merely to make this job run.

A dedicated RAM user's AccessKey is a simple initial credential option. If the
account already uses short-lived STS credentials, all three credential fields
must be supplied together and must remain valid through the job. Never copy
AccessKeys, tenant tokens, private keys, or passwords into repository files or
screenshots. Rotate/revoke the deployment credential after assessment; OIDC
federation is a future alternative, not implemented by this workflow.

## GitHub configuration

In the repository, open **Settings → Secrets and variables → Actions**. Add:

| Secret name | Content |
|---|---|
| `SAE_ACCESS_KEY_ID` | AccessKey ID of the dedicated RAM deployment identity |
| `SAE_ACCESS_KEY_SECRET` | Matching AccessKey secret |
| `SAE_SECURITY_TOKEN` | Optional STS session token; leave absent for a RAM user's AccessKey |

The existing `ACR_USERNAME` and `ACR_PASSWORD` remain separate. An ACR login
password is not a RAM AccessKey secret. Database and application authentication
values stay in SAE; they are not needed in GitHub by this deployment runner.

Create the GitHub environment `sae-evaluation` under **Settings → Environments**.
Restrict it to `main` where the account supports that feature. Required-reviewer
protection is optional and depends on GitHub plan/repository visibility. The
workflow itself also permits deployment only on `push` to `main`, never on PRs.

Optional repository variables `SAE_APP_ID` and `SAE_BASE_URL` override the
defaults above. The deployment gate is a **repository-level Actions variable**:

| Variable | Initial value |
|---|---|
| `SAE_DEPLOY_ENABLED` | `false`, or do not create it yet |

The job is skipped unless that variable is exactly `true`. Keep it disabled
while publishing and reviewing the workflow changes. Once enabled, subsequent
main-branch pushes that pass tests and publish ACR automatically request a
release. An explicit required-reviewer gate, if configured, precedes the job.

## Review release policy before enabling

The API request updates the image and explicitly selects rolling deployment:
`MinReadyInstances=1`, `MinReadyInstanceRatio=-1`, and `UpdateStrategy=""`.
This replaces the earlier manual gray/batch confirmation policy. At least two
existing replicas are required by the runner; it refuses a one-replica target.
It requests re-enabling the existing autoscaling policy after successful
publication via `AutoEnableApplicationScalingRule=true`.

The request omits CPU, memory, replicas, VPC, vSwitch, security group, command,
environment variables, probe configuration, image-pull credentials, and SLS
settings. It relies on retaining the application's existing configuration;
verify those settings and the current readiness probe before the first run.
No change to a CLB listener or the RDS schema is requested by this runner.

Jobs use a concurrency group without canceling an in-progress deployment.
Approval-required releases and manual-batch waits fail visibly instead of
being silently approved. A failed release does not trigger an automatic
rollback or a second deployment request. Inspect SAE before retrying,
particularly after a connection error that may hide an already-started release.

## First real run and evidence

1. Ensure the existing SAE application has at least two healthy replicas,
   `/ready` checks RDS successfully, and no release/fault experiment is running.
2. Review the rolling-release policy above and configure RAM/GitHub without
   exposing credentials.
3. Publish the reviewed workflow and runner while the deployment gate is off.
4. Enable repository variable `SAE_DEPLOY_ENABLED=true`, then push a reviewed
   commit to `main`. Never push an unreviewed application change just to trigger
   a deployment.
5. Verify `test`, `terraform`, `deployment-tests`, `publish-acr`, and `deploy-sae`
   succeed. The current Terraform job validates the separate AWS design; it
   does **not** rebuild or validate the real Alibaba Cloud environment.
6. Download the `sae-deployment-<commit>-<attempt>` artifact. It contains only
   an allowlist of release metadata: UTC timestamps, region/application ID,
   commit/image, previous image, change order, status, and probe verdicts.
   Full SAE application responses and SDK exception text are not saved.
7. Save the Actions run link, SAE successful-release view, matching image
   version, healthy instance list, and a synthetic business-flow smoke test.
   Only then mark automated cloud deployment as verified.

The script waits at most 15 minutes (plus bounded API/HTTP request latency);
the workflow job has a 20-minute limit. SDK deployment writes are not retried
automatically. On timeout or failure, inspect the existing SAE release, roll
back through SAE if needed, and verify that the autoscaling rule is active.
Do not assume a failed job canceled the cloud-side release. Disable
`SAE_DEPLOY_ENABLED` to stop future automatic deployment jobs, not to abort a
release already executing in SAE.

## Local checks without cloud changes

```powershell
.\.venv\Scripts\python.exe -m pip install ".[dev,deploy]"
.\.venv\Scripts\python.exe -m pytest tests/test_sae_deploy.py
.\.venv\Scripts\python.exe scripts/check_secrets.py
```

These tests use fake SDK responses and fake time, never a cloud credential.
The SDK serialization test checks that omitted runtime fields are not
accidentally emitted as empty lists, potentially clearing existing settings.

## Official references

- [DeployApplication parameters and permissions](https://help.aliyun.com/zh/sae/api-sae-2019-05-06-deployapplication)
- [DescribeApplicationConfig](https://help.aliyun.com/zh/sae/api-sae-2019-05-06-describeapplicationconfig)
- [DescribeChangeOrder statuses and permissions](https://help.aliyun.com/zh/sae/api-sae-2019-05-06-describechangeorder)
- [Release-order integration, failure and scaling behavior](https://help.aliyun.com/zh/sae/change-orders-1)

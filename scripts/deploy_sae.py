"""Update an existing SAE image, wait for its change order, and probe the edge.

No environment variables, credentials, replica counts, or networking settings
are copied from the application into a deployment request or evidence file.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener
from uuid import UUID


class DeploymentError(RuntimeError):
    pass


def response_data(body: dict) -> dict:
    if body.get("Success") is not True or str(body.get("Code")) != "200":
        # Never print Message, ErrorMessage, or a full SDK response: they may
        # contain runtime configuration or a signed request.
        raise DeploymentError("SAE API rejected the request; check RAM permissions and the SAE console")
    data = body.get("Data")
    if not isinstance(data, dict):
        raise DeploymentError("SAE API returned no structured Data")
    return data


def deployment_parameters(app_id: str, image: str, commit: str) -> dict:
    return {
        "AppId": app_id,
        "ImageUrl": image,
        "MinReadyInstances": 1,
        "MinReadyInstanceRatio": -1,
        "UpdateStrategy": "",
        "AutoEnableApplicationScalingRule": True,
        "ChangeOrderDesc": f"GitHub Actions commit {commit}",
    }


class SaeApi:
    def __init__(self, region: str):
        from alibabacloud_sae20190506 import models
        from alibabacloud_sae20190506.client import Client
        from alibabacloud_tea_openapi.utils_models import Config
        from darabonba.policy.retry import RetryOptions

        key_id = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
        key_secret = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
        if not key_id or not key_secret:
            raise DeploymentError("Missing SAE_ACCESS_KEY_ID or SAE_ACCESS_KEY_SECRET in GitHub Secrets")
        self.models = models
        self.client = Client(Config(
            access_key_id=key_id,
            access_key_secret=key_secret,
            security_token=os.environ.get("ALIBABA_CLOUD_SECURITY_TOKEN") or None,
            region_id=region,
            endpoint=f"sae.{region}.aliyuncs.com",
            connect_timeout=10_000,
            read_timeout=20_000,
            retry_options=RetryOptions(retryable=False, maxAttempts=1),
        ))

    def application(self, app_id: str) -> dict:
        request = self.models.DescribeApplicationConfigRequest(app_id=app_id)
        return response_data(self.client.describe_application_config(request).body.to_map())

    def deploy(self, app_id: str, image: str, commit: str) -> dict:
        from alibabacloud_tea_openapi.utils import Utils
        from alibabacloud_tea_openapi.utils_models import OpenApiRequest, Params
        from darabonba.runtime import RuntimeOptions

        # The pinned generated deploy wrapper emits empty sidecar/init lists
        # even when omitted. Use the SDK's signing/transport with an explicit
        # query allowlist, rather than clearing the existing container config.
        request = OpenApiRequest(query=Utils.query(deployment_parameters(app_id, image, commit)), body={})
        params = Params(action="DeployApplication", version="2019-05-06",
                        protocol="HTTPS", pathname="/pop/v1/sam/app/deployApplication",
                        method="POST", auth_type="AK", style="ROA",
                        req_body_type="formData", body_type="json")
        # Do not retry this write automatically: an uncertain response may
        # already have started a release.
        result = self.client.call_api(params, request, RuntimeOptions(autoretry=False, max_attempts=1))
        return response_data(result["body"])

    def change_order(self, order_id: str) -> dict:
        request = self.models.DescribeChangeOrderRequest(change_order_id=order_id)
        return response_data(self.client.describe_change_order(request).body.to_map())


def validate_inputs(app_id: str, region: str, image: str, commit: str, base_url: str, timeout: int):
    try:
        UUID(app_id)
    except ValueError:
        raise DeploymentError("Application ID must be a UUID") from None
    if not re.fullmatch(r"[a-z]{2}-[a-z0-9-]+", region):
        raise DeploymentError("Invalid SAE region")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise DeploymentError("A full lowercase 40-character Git commit is required")
    repository, separator, tag = image.rpartition(":")
    if not separator or tag != commit or "/" not in repository or not re.fullmatch(r"[a-zA-Z0-9._/:-]+", repository):
        raise DeploymentError("Image must use the requested Git commit tag, not latest")
    parsed = urlsplit(base_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise DeploymentError("Base URL must be an HTTP(S) origin without credentials or a path")
    if not 30 <= timeout <= 900:
        raise DeploymentError("Timeout must be between 30 and 900 seconds")


def probe(base_url: str, path: str, expected: str) -> bool:
    # Do not inherit a developer-machine HTTP proxy. HTTPS retains the
    # standard certificate and hostname validation; never use verify=False.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(base_url.rstrip("/") + path, timeout=5) as response:
            return response.status == 200 and json.loads(response.read(4096)).get("status") == expected
    except (OSError, ValueError, AttributeError):
        return False


def release(api, app_id: str, image: str, commit: str, base_url: str,
            evidence: dict, timeout: int = 900, *,
            clock=time.monotonic, sleep=time.sleep, health_probe=probe):
    deadline = clock() + timeout
    before = api.application(app_id)
    if before.get("AppId") != app_id or before.get("PackageType") != "Image":
        raise DeploymentError("Application ID or package type does not match the existing image application")
    if int(before.get("Replicas", 0)) < 2:
        raise DeploymentError("At least two existing replicas are required for this rolling-release policy")
    old_image = before.get("ImageUrl", "")
    old_repository = old_image.split("@", 1)[0].rsplit(":", 1)[0]
    if old_repository != image.rsplit(":", 1)[0]:
        raise DeploymentError("Refusing to change the application's image repository")
    evidence["previous_image"] = old_image
    evidence["phase"] = "deploy_request"
    result = api.deploy(app_id, image, commit)
    order_id = result.get("ChangeOrderId")
    if not order_id or result.get("AppId") != app_id:
        raise DeploymentError("Deployment response has no matching application/change order")
    evidence["change_order_id"] = order_id
    evidence["phase"] = "wait_change_order"
    if result.get("IsNeedApproval"):
        raise DeploymentError("Release needs SAE approval; it was not automatically approved")
    while clock() < deadline:
        order = api.change_order(order_id)
        if order.get("AppId") != app_id:
            raise DeploymentError("Change order belongs to a different application")
        status = int(order.get("Status", -1))
        evidence["change_order_status"] = status
        if int(order.get("SubStatus", 0)) == 1 or status in {3, 6, 10}:
            raise DeploymentError("Change order failed or was terminated; inspect SAE and restore scaling if needed")
        if status in {8, 11}:
            raise DeploymentError("Change order requires manual confirmation/approval; no automatic bypass was attempted")
        if status == 2:
            break
        if status not in {0, 1, 9, 12}:
            raise DeploymentError("Unrecognized change-order status")
        sleep(min(10, max(0, deadline - clock())))
    else:
        raise DeploymentError("Timed out waiting for the change order; inspect SAE before another release")
    evidence["phase"] = "verify_image"
    if api.application(app_id).get("ImageUrl") != image:
        raise DeploymentError("SAE image does not match the requested commit")
    evidence["phase"] = "health_checks"
    # Require three consecutive healthy pairs after the confirmed release.
    consecutive = 0
    while clock() < deadline:
        healthy = health_probe(base_url, "/health", "ok") and health_probe(base_url, "/ready", "ready")
        consecutive = consecutive + 1 if healthy else 0
        if consecutive == 3:
            evidence["health"] = "passed"
            evidence["readiness"] = "passed"
            evidence["status"] = "success"
            evidence["phase"] = "complete"
            return
        sleep(min(5, max(0, deadline - clock())))
    raise DeploymentError("Timed out waiting for public health/readiness; inspect SAE before another release")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--region", default="cn-beijing")
    parser.add_argument("--image", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--output", type=Path, default=Path("results/.local/sae-deployment.json"))
    args = parser.parse_args(argv)
    evidence = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "status": "failed", "phase": "preflight"}
    try:
        validate_inputs(args.app_id, args.region, args.image, args.commit, args.base_url, args.timeout)
        evidence.update({"application_id": args.app_id, "region": args.region,
                         "commit": args.commit, "requested_image": args.image,
                         "base_url": args.base_url,
                         "transport": "HTTPS" if args.base_url.startswith("https://") else "HTTP (TLS unverified)"})
        release(SaeApi(args.region), args.app_id, args.image, args.commit,
                args.base_url, evidence, args.timeout)
    except DeploymentError as error:
        evidence["error"] = str(error)
    except Exception as error:
        # SDK exception text can include signed URLs or sensitive parameters.
        evidence["error"] = f"Deployment stopped ({type(error).__name__}); inspect SAE before retrying"
    finally:
        evidence["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

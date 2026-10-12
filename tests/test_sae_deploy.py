from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_sae.py"
if not SCRIPT.is_file():
    pytest.skip("Deployment runner is not packaged in the application test image", allow_module_level=True)
spec = importlib.util.spec_from_file_location("deploy_sae", SCRIPT)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

APP = "1187c616-c49b-4b0f-8cec-2f9e45989acd"
COMMIT = "a" * 40
IMAGE = f"registry.example.test/team/heritageflow:{COMMIT}"
BASE = "http://192.0.2.1"


class FakeClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeApi:
    def __init__(self, statuses=(0, 1, 2), **config):
        self.config = {"AppId": APP, "PackageType": "Image", "Replicas": 2,
                       "ImageUrl": "registry.example.test/team/heritageflow:previous", **config}
        self.statuses = iter(statuses)
        self.last_status = 0
        self.writes = []
        self.approval = False
        self.substatus = 0

    def application(self, app_id):
        return {**self.config, "ImageUrl": IMAGE} if self.last_status == 2 else self.config

    def deploy(self, app_id, image, commit):
        self.writes.append(deploy.deployment_parameters(app_id, image, commit))
        return {"AppId": APP, "ChangeOrderId": "test-order", "IsNeedApproval": self.approval}

    def change_order(self, order_id):
        self.last_status = next(self.statuses, self.last_status)
        return {"AppId": APP, "Status": self.last_status, "SubStatus": self.substatus}


def run_release(api, probe=lambda *args: True, timeout=60):
    evidence = {"status": "failed"}
    clock = FakeClock()
    deploy.release(api, APP, IMAGE, COMMIT, BASE, evidence, timeout,
                   clock=clock, sleep=clock.sleep, health_probe=probe)
    return evidence


def test_success_waits_for_order_and_three_healthy_pairs():
    calls = []
    evidence = run_release(FakeApi(), probe=lambda *args: calls.append(args) or True)
    assert evidence["status"] == "success"
    assert evidence["change_order_status"] == 2
    assert len(calls) == 6


@pytest.mark.parametrize("status", [3, 6, 8, 10, 11, 99])
def test_failed_manual_and_unknown_statuses_are_not_success(status):
    with pytest.raises(deploy.DeploymentError):
        run_release(FakeApi((status,)))


def test_abnormal_substatus_fails_even_if_order_is_running():
    api = FakeApi((1,))
    api.substatus = 1
    with pytest.raises(deploy.DeploymentError, match="failed"):
        run_release(api)


def test_order_timeout_is_not_success():
    with pytest.raises(deploy.DeploymentError, match="Timed out waiting for the change order"):
        run_release(FakeApi((1,)))


def test_healthy_old_endpoint_cannot_hide_wrong_image():
    api = FakeApi((2,))
    api.application = lambda app_id: api.config
    with pytest.raises(deploy.DeploymentError, match="image does not match"):
        run_release(api)


def test_failed_readiness_is_not_success():
    with pytest.raises(deploy.DeploymentError, match="health/readiness"):
        run_release(FakeApi((2,)), probe=lambda base, path, expected: path == "/health")


def test_release_requires_three_consecutive_healthy_pairs():
    # first pair succeeds, second pair fails, then three complete pairs succeed
    outcomes = iter([True, True, False, True, True, True, True, True, True])
    calls = []
    def probe(*args):
        calls.append(args)
        return next(outcomes)
    assert run_release(FakeApi((2,)), probe=probe)["status"] == "success"
    assert len(calls) == 9


@pytest.mark.parametrize("config", [
    {"Replicas": 1}, {"PackageType": "PythonZip"},
    {"AppId": "wrong-application"}, {"ImageUrl": "another.registry/team/app:old"},
])
def test_preflight_rejects_unsafe_configuration_before_write(config):
    api = FakeApi(**config)
    with pytest.raises(deploy.DeploymentError):
        run_release(api)
    assert api.writes == []


def test_approval_is_not_bypassed():
    api = FakeApi()
    api.approval = True
    with pytest.raises(deploy.DeploymentError, match="not automatically approved"):
        run_release(api)


def test_parameters_do_not_overwrite_secrets_networking_or_replica_counts():
    params = deploy.deployment_parameters(APP, IMAGE, COMMIT)
    assert set(params) == {"AppId", "ImageUrl", "MinReadyInstances",
                           "MinReadyInstanceRatio", "UpdateStrategy",
                           "AutoEnableApplicationScalingRule", "ChangeOrderDesc"}
    assert params["MinReadyInstances"] == 1
    assert params["UpdateStrategy"] == ""


def test_pinned_sdk_sends_only_intended_parameters(monkeypatch):
    pytest.importorskip("alibabacloud_sae20190506.models")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "unit-test-id")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "unit-test-secret")
    api = deploy.SaeApi("cn-beijing")
    assert api.client._retry_options.retryable is False
    outgoing = []
    def fake_call(params, request, runtime):
        assert params.action == "DeployApplication"
        assert params.method == "POST"
        assert runtime.autoretry is False
        assert runtime.max_attempts == 1
        outgoing.append(request)
        return {"body": {"Success": True, "Code": "200", "Data": {
            "AppId": APP, "ChangeOrderId": "test-order", "IsNeedApproval": False}}}
    monkeypatch.setattr(api.client, "call_api", fake_call)
    api.deploy(APP, IMAGE, COMMIT)
    assert set(outgoing[0].query) == {"AppId", "ImageUrl", "MinReadyInstances", "MinReadyInstanceRatio",
                                    "UpdateStrategy", "AutoEnableApplicationScalingRule", "ChangeOrderDesc"}
    assert outgoing[0].body == {}


@pytest.mark.parametrize("status,body,expected", [
    (200, b'{"status":"ready"}', True),
    (503, b'{"status":"ready"}', False),
    (200, b'{"status":"ok"}', False),
    (200, b'not json', False),
    (200, b'[]', False),
])
def test_probe_requires_status_and_matching_json(status, body, expected, monkeypatch):
    from unittest.mock import MagicMock
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.__enter__.return_value = response
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr(deploy, "build_opener", lambda *args: opener)
    assert deploy.probe(BASE, "/ready", "ready") is expected


def test_runtime_environment_is_not_written_to_evidence():
    evidence = run_release(FakeApi(Envs='[{"name":"DB_PASSWORD","value":"runtime-only-secret"}]'))
    assert "runtime-only-secret" not in json.dumps(evidence)


@pytest.mark.parametrize("changes", [
    {"image": "registry.example.test/team/heritageflow:latest"},
    {"commit": "short-sha"}, {"app_id": "not-a-uuid"},
    {"base_url": "http://user:password@example.test"},
    {"base_url": "http://example.test?token=private"},
    {"region": "bad/region"}, {"timeout": 0},
])
def test_invalid_inputs_are_rejected(changes):
    inputs = dict(app_id=APP, region="cn-beijing", image=IMAGE, commit=COMMIT, base_url=BASE, timeout=60)
    with pytest.raises(deploy.DeploymentError):
        deploy.validate_inputs(**{**inputs, **changes})


@pytest.mark.parametrize("body", [
    {"Success": False, "Code": "403", "Message": "sensitive response"},
    {"Success": True, "Code": "200", "Data": None},
])
def test_api_rejections_are_sanitized(body):
    with pytest.raises(deploy.DeploymentError) as error:
        deploy.response_data(body)
    assert "sensitive response" not in str(error.value)


def test_main_saves_failure_without_sdk_secret_text(tmp_path, monkeypatch, capsys):
    def fail(region):
        raise RuntimeError("private-signed-request-and-key")
    monkeypatch.setattr(deploy, "SaeApi", fail)
    output = tmp_path / "report.json"
    assert deploy.main(["--app-id", APP, "--image", IMAGE, "--commit", COMMIT,
                        "--base-url", BASE, "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["status"] == "failed"
    assert "private-signed-request-and-key" not in output.read_text() + capsys.readouterr().out


def test_main_preserves_only_safe_sdk_error_code(tmp_path, monkeypatch):
    class FakeSdkError(Exception):
        code = "Forbidden.RAM"
    def fail(region):
        raise FakeSdkError("private-signed-request-and-key")
    monkeypatch.setattr(deploy, "SaeApi", fail)
    output = tmp_path / "report.json"
    assert deploy.main(["--app-id", APP, "--image", IMAGE, "--commit", COMMIT,
                        "--base-url", BASE, "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["error_code"] == "Forbidden.RAM"
    assert "private-signed-request-and-key" not in output.read_text()


def test_check_only_does_not_request_a_deployment(tmp_path, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(deploy, "SaeApi", lambda region: api)
    monkeypatch.setattr(deploy, "probe", lambda *args: True)
    output = tmp_path / "report.json"
    assert deploy.main(["--app-id", APP, "--image", IMAGE, "--commit", COMMIT,
                        "--base-url", BASE, "--check-only", "--output", str(output)]) == 0
    assert api.writes == []
    report = json.loads(output.read_text())
    assert report["mode"] == "check_only"
    assert report["phase"] == "check_complete"

"""Check image dependency parity without importing Modal or contacting its control plane."""

import ast
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_api_image_installs_cloud_runtime_dependencies():
    cloud = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((cloud / "pyproject.toml").read_text())["project"]["dependencies"]
    required = {re.split(r"[<>=!~\[]", requirement)[0] for requirement in declared}
    # Contracts are copied as source. Modal supplies its own runtime; uvicorn is the local server CLI.
    required -= {"kaiku-contracts", "modal", "uvicorn"}
    tree = ast.parse((cloud / "app.py").read_text())
    installed = {
        re.split(r"[<>=!~\[]", arg.value)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "pip_install"
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    }
    assert required <= installed, f"Modal API image omits runtime dependencies: {sorted(required - installed)}"


@pytest.mark.parametrize(("environment", "expected_app", "expected_volume"), [
    ({}, "kaiku", "kaiku-data"),
    ({"KAIKU_MODAL_APP": "kaiku-staging"}, "kaiku-staging", "kaiku-staging-data"),
    ({"KAIKU_MODAL_APP": "kaiku-staging", "KAIKU_MODAL_VOLUME": "reviewed-state"},
     "kaiku-staging", "reviewed-state"),
])
def test_deployment_isolates_app_state_unless_volume_reuse_is_explicit(environment, expected_app, expected_volume):
    """Evaluate actual deployment config without importing Modal or creating a remote app/Volume."""
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text())
    names = {"APP_NAME", "VOLUME_NAME", "ENV"}
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)]
    namespace = {"os": SimpleNamespace(environ=environment), "DATA": "/data", "LLM": "template", "SECRETS": []}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), "deployment-config", "exec"), namespace)
    assert namespace["APP_NAME"] == expected_app
    assert namespace["ENV"]["KAIKU_MODAL_VOLUME"] == expected_volume
    assert namespace["ENV"]["KAIKU_DB_PATH"] == "/data/kaiku.sqlite"
    volume_call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute) and node.func.attr == "from_name"
                       and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "Volume")
    assert eval(compile(ast.Expression(body=volume_call.args[0]), "volume-name", "eval"), namespace) == expected_volume


def test_modal_source_only_image_starts_with_explicit_runtime_assets(tmp_path):
    """Reproduce Modal's Python-only source packaging outside this checkout, then import the real API.

    Without the image's explicit prompt-directory copy this fails at explanation import, as the deployed
    service did. Config/persona/voice/safety files must also resolve from the staged image, not the checkout.
    """
    cloud = Path(__file__).resolve().parents[1]
    root = cloud.parent
    for source in (cloud / "kaiku_cloud", root / "contracts" / "python" / "kaiku_contracts"):
        for path in source.rglob("*.py"):
            target = tmp_path / source.name / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    tree = ast.parse((cloud / "app.py").read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_local_dir"):
            continue
        # The separately built static export is not required for API startup.
        if isinstance(node.args[0], ast.Name) and node.args[0].id == "WEB_OUT":
            continue
        source = eval(compile(ast.Expression(body=node.args[0]), "asset-source", "eval"), {"ROOT": root})
        target = tmp_path / Path(ast.literal_eval(node.args[1])).relative_to("/root")
        shutil.copytree(source, target, dirs_exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "KAIKU_DB_PATH": str(tmp_path / "api.sqlite"),
           "KAIKU_CONFIG": str(tmp_path / "config" / "kaiku.toml"),
           "KAIKU_CRITERIA": str(tmp_path / "config" / "criteria.toml"), "KAIKU_WEB_DIR": "",
           "KAIKU_HOME_TOKENS": "{}", "KAIKU_HOME_TOKEN": "", "KAIKU_CLINICIAN_TOKEN": "",
           "KAIKU_ADMIN_TOKEN": "", "KAIKU_DEMO_MODE": "0", "KAIKU_LLM": "template"}
    script = """
from pathlib import Path
from fastapi.testclient import TestClient
from kaiku_cloud.api.main import create_app
from kaiku_cloud.llm import explain
from kaiku_contracts.config import find_repo_file
assert Path(explain.__file__).is_relative_to(Path.cwd())
assert explain.PROMPT.strip()
for name in ('kaiku.toml', 'criteria.toml', 'persona.md', 'surfaces.toml', 'voice_lines.toml', 'safety_phrases.toml'):
    assert find_repo_file('config/' + name).is_relative_to(Path.cwd())
response = TestClient(create_app()).get('/healthz')
assert response.status_code == 200 and response.json()['db']
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_public_deployment_never_exposes_admin_or_care_routes_without_credentials(tmp_path):
    """Modal sets `deployed`. Without tokens and without explicit demo mode everything private is closed; a public
    demo opens reads only, and reset / criteria / paid admin jobs still need the admin credential."""
    from fastapi.testclient import TestClient
    from kaiku_cloud.api.main import create_app
    from kaiku_cloud.settings import Settings

    def client(name, **kw):
        base = {"db_path": str(tmp_path / f"{name}.sqlite"), "web_dir": None, "home_token": None, "admin_token": None,
                "clinician_token": None, "home_tokens": {}, "demo_mode": False, "deployed": True, "llm": "template"}
        return TestClient(create_app(Settings(**{**base, **kw})))

    admin_routes = [("post", "/v1/admin/reset"), ("post", "/v1/admin/recompute"), ("get", "/v1/admin/criteria"),
                    ("put", "/v1/admin/criteria"), ("post", "/v1/admin/weekly"), ("post", "/v1/admin/reflect"),
                    ("post", "/v1/admin/nightly-mind")]
    care_routes = ["/v1/patients", "/v1/patients/x/insight", "/v1/patients/x/consensus", "/v1/events", "/v1/eval",
                   "/v1/health/intelligence"]
    closed = client("closed")
    assert closed.get("/healthz").status_code == 200 and closed.get("/v1/discovery").json()["mode"] == "unconfigured"
    for method, path in admin_routes:
        assert getattr(closed, method)(path).status_code == 401, path
    for path in care_routes:
        assert closed.get(path).status_code == 401, path

    demo = client("demo", demo_mode=True, admin_token="admin-secret")
    assert demo.get("/v1/discovery").json()["mode"] == "demo" and demo.get("/v1/patients").status_code == 200
    for method, path in admin_routes:
        assert getattr(demo, method)(path).status_code == 401, path
        assert getattr(demo, method)(path, headers={"Authorization": "Bearer wrong"}).status_code == 401, path
    assert demo.post("/v1/admin/recompute", headers={"Authorization": "Bearer admin-secret"}).status_code == 200
    # a deployed demo with no admin credential keeps admin closed to everyone
    assert client("demo-no-admin", demo_mode=True).post("/v1/admin/reset").status_code == 401
    # locally nothing changes: demo mode with an admin credential configured is an authenticated service
    local = client("local", demo_mode=True, admin_token="admin-secret", deployed=False)
    assert local.get("/v1/patients").status_code == 401

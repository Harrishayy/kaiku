import pytest
from fastapi.testclient import TestClient
from kaiku_cloud.api.main import create_app
from kaiku_cloud.settings import Settings


@pytest.fixture
def make_client(tmp_path):
    def _make(**kw):
        s = Settings(db_path=str(tmp_path / "t.sqlite"), web_dir=kw.pop("web_dir", None), home_token=kw.pop("home_token", None),
                     admin_token=kw.pop("admin_token", None), clinician_token=kw.pop("clinician_token", None),
                     home_tokens=kw.pop("home_tokens", {}), home_id=kw.pop("home_id", "demo-aino"),
                     demo_mode=kw.pop("demo_mode", True), llm=kw.pop("llm", "template"))
        return TestClient(create_app(s, **kw))

    return _make


@pytest.fixture
def client(make_client):
    return make_client()

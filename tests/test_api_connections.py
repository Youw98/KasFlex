"""Credential persistence, isolation, and status-only API responses."""
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from kasflex.api_connections import ApiConnections
from kasflex.ui.server import serve


@pytest.fixture
def connections(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTSOE_API_KEY", "")
    return ApiConnections(tmp_path / ".env")


def test_persist_reload_remove_without_returning_secrets(connections, monkeypatch):
    result = connections.save("entsoe", "fixture-token")
    assert "fixture-token" not in json.dumps(result)
    assert result["connections"][0]["configured"]
    assert os.environ["ENTSOE_API_KEY"] == "fixture-token"
    monkeypatch.setenv("ENTSOE_API_KEY", "")
    ApiConnections(connections.path)
    assert os.environ["ENTSOE_API_KEY"] == "fixture-token"
    connections.save("entsoe", "", remove=True)
    assert "fixture-token" not in connections.path.read_text()
    assert not os.environ.get("ENTSOE_API_KEY")


def test_preserves_unrelated_env_and_rejects_injection(connections):
    with connections.path.open("a") as stream:
        stream.write("OTHER_SETTING=keep-me\n")
    connections.save("entsoe", "fixture-token")
    assert "OTHER_SETTING=keep-me" in connections.path.read_text()
    with pytest.raises(ValueError):
        connections.save("entsoe", "token\nOTHER_SETTING=replaced")
    with pytest.raises(ValueError):
        connections.save("openai", "unused-key")


def test_inherited_environment_takes_precedence(connections, monkeypatch):
    connections.save("entsoe", "file-token")
    monkeypatch.setenv("ENTSOE_API_KEY", "environment-token")
    ApiConnections(connections.path)
    assert os.environ["ENTSOE_API_KEY"] == "environment-token"


def test_local_endpoint_saves_and_refuses_cross_origin(tmp_path, monkeypatch):
    config = Path("configs/scenario_westland_winter.yaml").resolve()
    monkeypatch.setenv("ENTSOE_API_KEY", "")
    monkeypatch.chdir(tmp_path)
    server = serve(config_path=str(config), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        data = json.dumps({"provider": "entsoe", "api_key": "fixture-token"}).encode()
        headers = {"Content-Type": "application/json", "Origin": root}
        request = urllib.request.Request(root + "/api/connections", data, headers)
        with urllib.request.urlopen(request) as response:
            body = response.read().decode()
        assert "fixture-token" not in body
        assert json.loads(body)["connections"][0]["configured"]
        headers["Origin"] = "https://unrelated.example"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(urllib.request.Request(root + "/api/connections", data, headers))
        assert exc.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(root + "/.env")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

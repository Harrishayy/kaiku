"""Shared pytest fixtures. `broker` starts a throwaway mosquitto on a free port (skips if not installed)."""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest


def _mosquitto() -> str | None:
    for c in (shutil.which("mosquitto"), "/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto", "/usr/sbin/mosquitto"):
        if c and Path(c).exists():
            return c
    return None


@pytest.fixture
def broker(tmp_path, monkeypatch):
    exe = _mosquitto()
    if not exe:
        pytest.skip("mosquitto not installed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    conf = tmp_path / "m.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    proc = subprocess.Popen([exe, "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.05)
    monkeypatch.setenv("MQTT_HOST", "127.0.0.1")
    monkeypatch.setenv("MQTT_PORT", str(port))
    os.environ.pop("MQTT_USER", None)
    yield {"host": "127.0.0.1", "port": port}
    proc.terminate()
    proc.wait(timeout=5)

"""Run the local API with a distinct Bonjour service; never advertise credentials or a home ID."""
from __future__ import annotations

import argparse
import json
import shutil
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from kaiku_contracts.api import APIDiscoveryResponse
from kaiku_contracts.config import get, load_dotenv
from kaiku_contracts.jlog import get_logger

log = get_logger("local_api")


def advertise_command(name: str, port: int) -> list[str] | None:
    # This service identifies the API, not a robot and not a permission to access records.
    txt = ["service=kaiku-api", "path=/v1/discovery", "scheme=http", "v=1"]
    if binary := shutil.which("dns-sd"):
        return [binary, "-R", name, "_kaiku-api._tcp", "local.", str(port), *txt]
    if binary := shutil.which("avahi-publish-service"):
        return [binary, name, "_kaiku-api._tcp", str(port), *txt]
    return None


def ready(port: int, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                healthy = response.status == 200 and json.load(response).get("status") == "ok"
            if healthy:
                with urlopen(f"http://127.0.0.1:{port}/v1/discovery", timeout=1) as response:
                    APIDiscoveryResponse.model_validate(json.load(response))
                    return response.status == 200
        except (URLError, TimeoutError, ValueError, OSError):
            pass
        time.sleep(0.2)
    return False


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=str(get("local_api", "host", "0.0.0.0")))
    parser.add_argument("--port", type=int, default=int(get("local_api", "port", 8000)))
    parser.add_argument("--name", default=str(get("local_api", "service_name", "Kaiku companion service")))
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--advertise-only", action="store_true", help="advertise an already-running local API")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    def terminate(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    server = announcement = None
    try:
        if not args.advertise_only:
            # The apps keep GET /v1/me/stream open (D50). Without a limit a stop or a --reload restart would wait
            # for every open stream to end by itself; with it they are cut and the apps reconnect.
            command = [sys.executable, "-m", "uvicorn", "kaiku_cloud.api.local:app", "--host", args.host,
                       "--port", str(args.port), "--timeout-graceful-shutdown",
                       str(int(get("local_api", "graceful_shutdown_s", 3)))]
            if args.reload:
                command.append("--reload")
            server = subprocess.Popen(command)
        if not ready(args.port) or (server is not None and server.poll() is not None):
            log.error("not_ready", port=args.port)
            return 1
        command = advertise_command(args.name, args.port)
        if command:
            announcement = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("discovery_started", service="_kaiku-api._tcp", port=args.port)
        else:
            log.warning("discovery_unavailable", hint="install Bonjour/dns-sd or avahi-publish-service")
        if server:
            return server.wait()
        return announcement.wait() if announcement else 1
    except KeyboardInterrupt:
        return 0
    finally:
        stop(announcement)
        stop(server)


if __name__ == "__main__":
    raise SystemExit(main())

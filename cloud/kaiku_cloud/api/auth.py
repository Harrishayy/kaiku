"""Fail-closed route authorization. Pairing credentials are scoped to one home; care roles are separate."""
from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from ..settings import Settings


class Access:
    def __init__(self, settings: Settings):
        self.homes = dict(settings.home_tokens)
        if settings.home_token:
            self.homes[settings.home_id] = settings.home_token
        self.admin = settings.admin_token
        self.clinician = settings.clinician_token
        tokens = [*self.homes.values(), *[t for t in (self.admin, self.clinician) if t]]
        if len(tokens) != len(set(tokens)):
            raise ValueError("Each home and role must have a distinct credential")
        self.deployed = settings.deployed
        # Local demo: no credentials at all. On a public deployment a demo may keep an admin credential, so the
        # scheduled jobs still work while /v1/admin/* stays closed to everyone else.
        gate = [*self.homes.values(), *([self.clinician] if self.clinician else []),
                *([self.admin] if self.admin and not self.deployed else [])]
        self.demo = settings.demo_mode and not gate

    def identity(self, token: str | None) -> tuple[str, str | None] | None:
        if self.demo:
            return ("demo", None)
        if not token:
            return None
        for role, expected in (("admin", self.admin), ("clinician", self.clinician)):
            if expected and hmac.compare_digest(token, expected):
                return (role, None)
        for home, expected in self.homes.items():
            if hmac.compare_digest(token, expected):
                return ("home", home)
        return None

    def home_allowed(self, token: str | None, home: str) -> bool:
        identity = self.identity(token)
        return identity is not None and (identity[0] == "demo" or identity == ("home", home))

    async def authorize(self, request: Request) -> JSONResponse | None:
        path, method = request.url.path, request.method
        if not path.startswith("/v1/") or method == "OPTIONS" or path in ("/v1/voice", "/v1/discovery"):
            return None
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else None
        if self.demo and self.deployed and path.startswith("/v1/admin/"):
            # A deployed demo is public: reset, criteria overrides and paid jobs always need the admin credential.
            if not (self.admin and token and hmac.compare_digest(token, self.admin)):
                return JSONResponse({"detail": "admin credential required on a deployed service"}, status_code=401)
            return None
        identity = self.identity(token)
        if identity is None:
            return JSONResponse({"detail": "valid authorization required"}, status_code=401)
        role, own_home = identity
        if role == "demo":
            return None
        if path.startswith("/v1/admin/"):
            allowed = role == "admin"
        elif path == "/v1/patients" or path.startswith("/v1/patients/") or path in (
                "/v1/health", "/v1/health/intelligence", "/v1/eval"):
            allowed = role in ("clinician", "admin")
        elif path.startswith("/v1/voice/"):
            allowed = role == "home"
        elif path == "/v1/events" and method == "GET" and role in ("clinician", "admin"):
            allowed = True
        else:
            homes = [request.query_params.get("home_id")]
            if path.startswith("/v1/health/") and method == "PUT":
                homes = [path.removeprefix("/v1/health/")]
            elif path.startswith("/v1/companion/") or (path == "/v1/events" and method == "POST"):
                try:
                    body = await request.json()
                except Exception:
                    body = None
                if path == "/v1/events":
                    events = body.get("events", []) if isinstance(body, dict) else []
                    homes = [e.get("home_id") for e in events if isinstance(e, dict)] if isinstance(events, list) else []
                else:
                    homes = [body.get("home_id")] if isinstance(body, dict) else []
            elif path.startswith("/v1/me/postcards/"):
                # These images contain only generic activity stats, never notebook content.
                homes = [own_home]
            allowed = role == "home" and all(home == own_home for home in homes)
        if not allowed:
            return JSONResponse({"detail": "credential does not authorize this home or role"}, status_code=403)
        return None

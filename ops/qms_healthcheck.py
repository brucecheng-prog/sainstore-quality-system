#!/usr/bin/env python3
"""Read-only QMS release health check.

Checks the approved QMS entry points without writing business data.  A healthy
unified instance must expose /healthz and report that Cookie and photo token
configuration are present.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


ENDPOINTS = {
    "developer": "http://localhost:8501/healthz",
    "lan": "http://192.168.61.16:8501/healthz",
    "public": "http://219.131.130.146:8501/healthz",
}


def check(name: str, url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"{name}: FAIL connection: {exc}")
        return False

    if status != 200 or "application/json" not in content_type:
        print(f"{name}: FAIL expected JSON health response, got HTTP {status} {content_type}")
        return False
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        print(f"{name}: FAIL invalid JSON health response")
        return False

    required = ("ok", "environment", "photo_token_configured", "cookie_secret_configured")
    missing = [key for key in required if key not in payload]
    if missing or not payload.get("ok") or not payload.get("photo_token_configured") or not payload.get("cookie_secret_configured"):
        print(f"{name}: FAIL unhealthy payload (missing={missing})")
        return False

    print(f"{name}: PASS environment={payload['environment']} instance={payload.get('instance', 'unspecified')}")
    return True


def main() -> int:
    results = [check(name, url) for name, url in ENDPOINTS.items()]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

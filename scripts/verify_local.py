"""Read-only runtime health and verification summary (never prints credentials)."""

import json

import httpx

for path in ["/health", "/ready", "/api/settings", "/api/dashboard/summary"]:
    r = httpx.get("http://127.0.0.1:8010" + path, timeout=10)
    print(path, r.status_code, json.dumps(r.json()))

#!/usr/bin/env python3
"""Quick IDE functional smoke test against VM API."""
import httpx

BASE = "http://ravenna-vm:8000"

def main() -> None:
    with httpx.Client(timeout=90, base_url=BASE) as c:
        checks = [
            ("GET", "/health", None, None),
            ("GET", "/api/agents", None, None),
            ("GET", "/api/agents/autonomy/always-on", None, None),
            ("GET", "/api/workspace/roots", None, None),
            ("GET", "/api/workspace/files", None, {"path": ""}),
            ("GET", "/api/chat/conversations", None, None),
            ("GET", "/api/ide/parity", None, None),
            ("GET", "/api/raven/readiness", None, None),
            ("POST", "/api/chat", {"message": "oi", "model_size": "0.5b", "mode": "chat"}, None),
        ]
        for method, path, body, params in checks:
            try:
                r = c.request(method, path, json=body, params=params)
                snippet = r.text[:100].replace("\n", " ")
                print(f"{method:4} {path:40} {r.status_code}  {snippet}")
            except Exception as exc:
                print(f"{method:4} {path:40} ERR   {exc}")

        if True:
            p = c.get("/api/ide/parity").json()
            passed = p.get("score", 0)
            total = p.get("total", 0)
            print(f"\nParity: {passed}/{total}")
            for d in p.get("dimensions", []):
                mark = "OK" if d.get("ok") else "--"
                print(f"  {mark} {d.get('label')}")

if __name__ == "__main__":
    main()

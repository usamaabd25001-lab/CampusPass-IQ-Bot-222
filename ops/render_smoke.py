from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import urljoin

import httpx


async def expect_status(client: httpx.AsyncClient, path: str, expected: int) -> httpx.Response:
    response = await client.get(path)
    if response.status_code != expected:
        raise RuntimeError(f"GET {path} returned {response.status_code}, expected {expected}")
    return response


async def main() -> int:
    base_url = (
        os.environ.get("SMOKE_BASE_URL", "").strip()
        or os.environ.get("PUBLIC_BASE_URL", "").strip()
        or os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    ).rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("SMOKE_BASE_URL must be an HTTPS URL")
    admin_token = os.environ.get("API_ADMIN_TOKEN", "").strip()
    webhook_path = "/" + os.environ.get("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook").strip().strip("/")

    timeout = httpx.Timeout(12.0, connect=5.0)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout, follow_redirects=False) as client:
        ping = await expect_status(client, "/ping", 200)
        live = await expect_status(client, "/health/live", 200)
        ready = None
        for _ in range(40):
            candidate = await client.get("/health/ready")
            if candidate.status_code == 200:
                ready = candidate
                break
            await asyncio.sleep(3)
        if ready is None:
            raise RuntimeError("/health/ready did not become healthy within 120 seconds")

        # A forged Telegram delivery must be rejected before its body is parsed or persisted.
        forged = await client.post(
            webhook_path,
            content=b'{}',
            headers={
                "content-type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": "invalid-smoke-secret",
            },
        )
        if forged.status_code not in {403, 404}:
            raise RuntimeError(f"Forged Telegram webhook returned {forged.status_code}")

        deep = None
        update_status = None
        if admin_token:
            headers = {"Authorization": f"Bearer {admin_token}"}
            deep = await client.get("/health/deep", headers=headers)
            if deep.status_code != 200:
                raise RuntimeError(f"Deep health gate failed with {deep.status_code}: {deep.text[:500]}")
            update_status = await client.get("/admin/update/status", headers=headers)
            if update_status.status_code != 200:
                raise RuntimeError(
                    f"Update compatibility status failed with {update_status.status_code}: "
                    f"{update_status.text[:500]}"
                )
            payload = update_status.json()
            if payload.get("draining"):
                raise RuntimeError("Runtime is unexpectedly draining during smoke test")

    print("CampusPass Render smoke passed")
    print(f"base_url={base_url}")
    print(f"version={ping.json().get('version')}")
    print(f"live={live.json().get('status')}")
    print(f"ready={ready.json().get('status')}")
    if deep is not None:
        print(f"deep_gate={deep.json().get('ok')}")
    if update_status is not None:
        print(f"update_contract={update_status.json().get('status', 'available')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"Render smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

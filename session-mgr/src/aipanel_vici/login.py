"""Playwright-driven first login.

Strategy
--------

Spinning up Chromium per login is too expensive at 1000-deployment scale,
but a single shared browser with N contexts gives us isolation between
concurrent logins (each context has its own cookie jar) at the cost of one
~200 MB Chromium process.

The pool is created once at startup; ``acquire`` blocks if all contexts
are busy. Contexts are reused across logins — ``release`` clears cookies
between uses so we don't accidentally inherit a previous deployment's
session.

Fail-soft: if Playwright isn't importable (test environments, CI without
chromium), construction raises a clear error rather than failing on first
``login_once`` call.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from .adapters.base import AdapterError, VicidialAdapter
from .adapters.v2_14 import base_url_from
from .models import CapturedSession, DeploymentRow

if TYPE_CHECKING:                                            # pragma: no cover
    from playwright.async_api import Browser, BrowserContext

log = structlog.get_logger().bind(component="login")


class PlaywrightUnavailable(RuntimeError):
    pass


class BrowserPool:
    """Single browser, N persistent contexts."""

    def __init__(self, size: int = 3, browsers_path: str | None = None) -> None:
        self._size = size
        self._available: asyncio.Queue["BrowserContext"] = asyncio.Queue(maxsize=size)
        self._pw: Any = None
        self._browser: "Browser | None" = None
        if browsers_path:
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers_path)

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:                           # pragma: no cover
            raise PlaywrightUnavailable(
                "playwright not installed in this venv; "
                "run `playwright install chromium` from session-mgr/.venv"
            ) from exc

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        for _ in range(self._size):
            ctx = await self._browser.new_context(
                user_agent=_AIPANEL_UA,
                ignore_https_errors=True,    # many vici installs use self-signed
            )
            await self._available.put(ctx)
        log.info("browser_pool_ready", size=self._size)

    async def acquire(self) -> "BrowserContext":
        return await self._available.get()

    async def release(self, ctx: "BrowserContext") -> None:
        try:
            await ctx.clear_cookies()
        except Exception:                                    # pragma: no cover
            log.exception("ctx_clear_cookies_failed")
        await self._available.put(ctx)

    async def stop(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:                                # pragma: no cover
                log.exception("browser_close_failed")
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:                                # pragma: no cover
                log.exception("playwright_stop_failed")
            self._pw = None


_AIPANEL_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 aipanel-session-mgr/0.6"
)


# ---------------------------------------------------------------------------
# Single login flow
# ---------------------------------------------------------------------------

async def login_once(
    pool: BrowserPool,
    adapter: VicidialAdapter,
    deployment: DeploymentRow,
    *,
    timeout_sec: float = 30.0,
    screenshot_dir: str | None = None,
) -> CapturedSession:
    """Drive a single login. Returns the captured cookies + session vars."""

    ctx = await pool.acquire()
    page = None
    try:
        page = await ctx.new_page()
        page.set_default_timeout(int(timeout_sec * 1000))

        base = base_url_from(deployment.web_url)
        login_url = adapter.login_url(base)

        log.info("login_navigate", deployment_id=str(deployment.deployment_id),
                 url=login_url)
        await page.goto(login_url, wait_until="domcontentloaded")

        # Fill the form. Each field is matched by `name=` attribute since
        # ViciDial has stable field names — IDs are sometimes missing in
        # custom themes.
        for name, value in adapter.login_form_fields(deployment).items():
            try:
                await page.fill(f'input[name="{name}"]', str(value))
            except Exception:
                # Some fields are hidden / absent — skip silently.
                log.debug("login_field_missing", name=name)

        # Submit. ViciDial 2.14's button is type="submit" with value "SUBMIT".
        # Fall back to pressing Enter inside a known input.
        try:
            await page.click('input[type="submit"]')
        except Exception:
            await page.press('input[name="VD_login"]', "Enter")

        # Wait for the agent UI to render — conf_exten= var appears in the
        # HTML once vicidial.php is in agent mode rather than login mode.
        try:
            await page.wait_for_function(
                'typeof conf_exten !== "undefined"',
                timeout=int(timeout_sec * 1000),
            )
        except Exception as exc:
            await _maybe_screenshot(page, screenshot_dir,
                                    deployment.deployment_id, "no_conf_exten")
            raise AdapterError(
                f"agent UI did not render conf_exten within {timeout_sec}s"
            ) from exc

        html = await page.content()
        cookies = await ctx.cookies(base)
        cookie_jar = {c["name"]: c["value"] for c in cookies if c.get("name")}

        captured = adapter.parse_agent_page(html, cookie_jar)
        captured.user_agent = _AIPANEL_UA

        log.info("login_ok",
                 deployment_id=str(deployment.deployment_id),
                 conf_exten=captured.conf_exten,
                 session_id=captured.session_id[:8] + "…")
        return captured
    except AdapterError:
        raise
    except Exception as exc:
        await _maybe_screenshot(page, screenshot_dir,
                                deployment.deployment_id, "exception")
        raise AdapterError(f"playwright login failed: {exc}") from exc
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:                                # pragma: no cover
                pass
        await pool.release(ctx)


async def _maybe_screenshot(
    page,
    screenshot_dir: str | None,
    deployment_id,
    tag: str,
) -> None:
    if page is None or not screenshot_dir:
        return
    try:
        d = Path(screenshot_dir)
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = d / f"{deployment_id}-{tag}-{ts}.png"
        await page.screenshot(path=str(path), full_page=True)
        log.warning("login_screenshot_saved", path=str(path))
    except Exception:                                        # pragma: no cover
        log.exception("login_screenshot_failed")

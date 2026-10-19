"""Playwright browser session with the bot's own persistent profile.

The profile (data/rewards/profile) keeps the Microsoft sign-in between runs,
so the user signs in once with ``python -m rewards_bot login``. Runs are
headless by default: no window, no focus stealing, no mouse or keyboard use.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .config import Settings
from .dashboard import DashboardError, DashboardState, parse_dashboard

log = logging.getLogger("rewards_bot.browser")

REWARDS_HOME = "https://rewards.bing.com/"
# The new dashboard lists activities on /earn, the old one on the home page.
REWARDS_ACTIVITY_PAGES = ("https://rewards.bing.com/earn", "https://rewards.bing.com/")
USERINFO_API = "https://rewards.bing.com/api/getuserinfo?type=1"
BING_HOME = "https://www.bing.com/"
BING_SIGNIN = ("https://www.bing.com/fd/auth/signin?action=interactive&provider=windows_live_id"
               "&return_url=https%3A%2F%2Fwww.bing.com%2F")
LOGIN_HOSTS = ("login.live.com", "login.microsoftonline.com", "login.microsoft.com",
               "account.live.com")

# Chrome's reduced mobile user agent (Edge for Android flavour).
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/{major}.0.0.0 Mobile Safari/537.36 EdgA/{major}.0.0.0")
MOBILE_DEVICE = {"viewport": {"width": 412, "height": 915}, "device_scale_factor": 2.625,
                 "is_mobile": True, "has_touch": True}

CONSENT_BUTTONS = ("#bnp_btn_accept", "#onetrust-accept-btn-handler")


class BrowserStartError(RuntimeError):
    pass


class SessionExpired(RuntimeError):
    pass


def chrome_major(user_agent: str) -> Optional[str]:
    match = re.search(r"(?:Headless)?Chrome/(\d+)", user_agent)
    return match.group(1) if match else None


def desired_user_agent(current: str, mobile: bool) -> str:
    """The UA a normal (non-headless) browser of the same version would send."""
    if mobile:
        return MOBILE_UA.format(major=chrome_major(current) or "130")
    return current.replace("HeadlessChrome/", "Chrome/")


def is_login_url(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOGIN_HOSTS


class BrowserSession:
    """``with BrowserSession(settings) as s:`` - one browser for one platform."""

    def __init__(self, settings: Settings, mobile: bool = False,
                 headless: Optional[bool] = None, today: Optional[date] = None):
        self.settings = settings
        self.mobile = mobile
        self.headless = settings.headless if headless is None else headless
        self.today = today
        self._pw = None
        self.context = None
        self.page = None

    # -- lifecycle -------------------------------------------------------------

    def __enter__(self) -> "BrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserStartError(
                "Playwright kurulu değil: pip install -r rewards_bot/requirements.txt") from exc
        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self.context = self._launch(user_agent=None)
            page = self._first_page()
            current = page.evaluate("() => navigator.userAgent")
            wanted = desired_user_agent(current, self.mobile)
            if wanted != current:
                # The UA is fixed per context, so relaunch with the corrected one.
                self.context.close()
                self.context = self._launch(user_agent=wanted)
            self.page = self._first_page()
            self.page.set_default_timeout(30_000)
        except Exception:
            self.close()
            raise
        log.debug("Tarayıcı açıldı (%s, %s)", "mobil" if self.mobile else "masaüstü",
                  "görünmez" if self.headless else "görünür")
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def _launch_kwargs(self, user_agent: Optional[str]) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "user_data_dir": str(self.settings.profile_dir),
            "headless": self.headless,
            "locale": self.settings.locale,
            "args": ["--mute-audio", "--disable-notifications", "--no-first-run",
                     "--no-default-browser-check"],
        }
        if not self.mobile:
            kwargs["viewport"] = {"width": 1366, "height": 768}
        else:
            kwargs.update(MOBILE_DEVICE)
        if user_agent:
            kwargs["user_agent"] = user_agent
        if self.settings.executable_path:
            kwargs["executable_path"] = self.settings.executable_path
        elif self.settings.browser != "chromium":
            kwargs["channel"] = self.settings.browser
        return kwargs

    def _launch(self, user_agent: Optional[str]):
        kwargs = self._launch_kwargs(user_agent)
        chromium = self._pw.chromium
        try:
            return chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            if "channel" not in kwargs:
                raise BrowserStartError(f"Tarayıcı başlatılamadı: {exc}") from exc
            log.warning("%s başlatılamadı, Playwright Chromium deneniyor: %s",
                        kwargs["channel"], str(exc).splitlines()[0])
            kwargs.pop("channel")
            try:
                return chromium.launch_persistent_context(**kwargs)
            except Exception as exc2:
                raise BrowserStartError(
                    "Tarayıcı başlatılamadı. Microsoft Edge kurulu mu? Değilse "
                    "`python -m playwright install chromium` çalıştırıp config.json'da "
                    f"\"browser\": \"chromium\" yapın. Ayrıntı: {exc2}") from exc2

    def _first_page(self):
        pages = self.context.pages
        return pages[0] if pages else self.context.new_page()

    # -- navigation --------------------------------------------------------------

    def goto(self, url: str, page=None, settle_ms: int = 8_000) -> None:
        page = page or self.page
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        try:
            page.wait_for_load_state("networkidle", timeout=settle_ms)
        except Exception:
            pass  # busy pages never go idle; the DOM is enough

    def on_login_page(self, page=None) -> bool:
        return is_login_url((page or self.page).url)

    def dismiss_consent(self, page=None) -> None:
        page = page or self.page
        for selector in CONSENT_BUTTONS:
            try:
                button = page.locator(selector).first
                if button.is_visible():
                    button.click(timeout=3_000)
            except Exception:
                pass

    def open_rewards(self) -> None:
        """Load the dashboard so the browser refreshes its Microsoft sign-in."""
        self.goto(REWARDS_HOME)
        if self.on_login_page():
            raise SessionExpired("Microsoft oturumu kapalı. Bir kez "
                                 "`python -m rewards_bot login` çalıştırıp giriş yapın.")

    def ensure_bing_signed_in(self) -> bool:
        """Searches only earn points when bing.com itself is signed in."""
        try:
            self.goto(BING_SIGNIN)
        except Exception as exc:
            log.debug("Bing oturum açma sayfası yüklenemedi: %s", exc)
        if self.on_login_page():
            raise SessionExpired("Bing oturumu açılamadı; `python -m rewards_bot login` çalıştırın.")
        self.dismiss_consent()
        signed_in = any(c.get("name") == "_U" for c in self.context.cookies(BING_HOME))
        if not signed_in:
            log.warning("bing.com'da oturum açık görünmüyor; aramalar puan kazandırmayabilir.")
        return signed_in

    # -- data ----------------------------------------------------------------------

    def read_dashboard_payload(self) -> Optional[Dict[str, Any]]:
        try:
            response = self.context.request.get(
                USERINFO_API, headers={"Referer": REWARDS_HOME}, timeout=30_000)
        except Exception as exc:
            log.warning("Puan bilgisi alınamadı: %s", exc)
            return None
        if not response.ok:
            log.warning("Puan bilgisi alınamadı: HTTP %s", response.status)
            return None
        try:
            return response.json()
        except Exception:
            log.warning("Puan bilgisi JSON değil (oturum kapalı olabilir)")
            return None

    def read_dashboard(self) -> Optional[DashboardState]:
        payload = self.read_dashboard_payload()
        if payload is None:
            return None
        try:
            return parse_dashboard(payload, self.today or date.today())
        except DashboardError as exc:
            log.warning("Puan bilgisi okunamadı: %s", exc)
            return None

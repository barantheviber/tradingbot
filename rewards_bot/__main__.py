"""Command line.

    python -m rewards_bot login          # once: sign in to Microsoft in a visible window
    python -m rewards_bot run            # collect today's points (headless, in the background)
    python -m rewards_bot status         # points, search counters, open activities
    python -m rewards_bot install-task   # run automatically every day (Windows Task Scheduler)
    python -m rewards_bot uninstall-task
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from typing import List, Optional

from . import __version__
from .browser import REWARDS_HOME, BrowserSession, BrowserStartError, SessionExpired
from .config import ConfigError, Settings, load_settings
from .dashboard import pending_activities
from .runner import PARTS, run_once
from .scheduler import install_task, uninstall_task
from .util import (AlreadyRunning, RunLock, done_today, lower_process_priority, read_state,
                   setup_logging, write_state)

LOGIN_TIMEOUT_SEC = 15 * 60


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m rewards_bot",
                                     description="Microsoft Rewards günlük puan botu")
    parser.add_argument("--config", help="Ayar dosyası (varsayılan: rewards_bot/config.json)")
    parser.add_argument("--verbose", action="store_true", help="Ayrıntılı log")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Microsoft hesabına bir kez giriş yap (görünür pencere)")
    run = sub.add_parser("run", help="Bugünün puanlarını topla")
    run.add_argument("--once-per-day", action="store_true",
                     help="Bugün zaten başarıyla çalıştıysa hiçbir şey yapma")
    run.add_argument("--visible", action="store_true", help="Tarayıcı penceresini göster")
    run.add_argument("--only", help=f"Yalnızca bunlar (virgülle): {','.join(PARTS)}")
    sub.add_parser("status", help="Puan ve kalan görevleri göster")
    sub.add_parser("install-task", help="Her gün otomatik çalışacak görevi kur")
    sub.add_parser("uninstall-task", help="Otomatik görevi kaldır")
    return parser.parse_args(argv)


def notify(message: str) -> None:
    """Scheduled runs have no console: show problems that need the user."""
    if sys.platform == "win32" and sys.stderr is None:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "Rewards bot", 0x30)  # type: ignore[attr-defined]
        except Exception:
            pass


def cmd_login(settings: Settings, log) -> int:
    print("Bir tarayıcı penceresi açılacak. Microsoft hesabınızla giriş yapın ve "
          "'Oturumum açık kalsın' seçeneğini işaretleyin. Rewards'a kayıtlı değilseniz "
          "sayfadaki katılma adımlarını tamamlayın. Giriş algılanınca pencere kendiliğinden kapanır.")
    with BrowserSession(settings, headless=False) as session:
        state = None
        try:
            session.goto(REWARDS_HOME)
            deadline = time.monotonic() + LOGIN_TIMEOUT_SEC
            while time.monotonic() < deadline:
                if not session.on_login_page():
                    state = session.read_dashboard()
                    if state is not None:
                        break
                session.page.wait_for_timeout(3_000)
            if state is not None:
                session.ensure_bing_signed_in()
        except SessionExpired:
            raise
        except Exception as exc:
            if state is None:
                print(f"Giriş tamamlanmadan pencere kapandı ya da bir hata oluştu: {exc}")
                return 1
        if state is None:
            print("Giriş algılanamadı (15 dk). Komutu yeniden çalıştırın.")
            return 1
    log.info("Giriş başarılı. Mevcut puan: %d", state.available_points)
    print(f"Giriş başarılı. Mevcut puan: {state.available_points}\n"
          "Şimdi `python -m rewards_bot run` ile deneyebilir, "
          "`python -m rewards_bot install-task` ile her gün otomatik çalıştırabilirsiniz.")
    return 0


def cmd_status(settings: Settings) -> int:
    with BrowserSession(settings) as session:
        session.open_rewards()
        state = session.read_dashboard()
    if state is None:
        print("Rewards paneli okunamadı.")
        return 1
    print(f"Toplam puan: {state.available_points}")
    for name, counter in (("Masaüstü arama", state.pc_search), ("Mobil arama", state.mobile_search)):
        print(f"{name}: " + (f"{counter.points}/{counter.maximum}" if counter else "yok"))
    todo = pending_activities(state, settings.daily_set, settings.more_activities)
    print(f"Yapılmamış görev: {len(todo)}")
    for promo in todo:
        print(f"  - {promo.title or promo.offer_id} ({promo.max_points - promo.points} puan, "
              f"{promo.promotion_type or '?'})")
    return 0


def cmd_run(settings: Settings, args, log) -> int:
    today = date.today()
    state = read_state(settings.state_file)
    if args.once_per_day and done_today(state, today):
        log.info("Bugün zaten tamamlandı, çıkılıyor.")
        return 0
    parts = None
    if args.only:
        parts = [p.strip() for p in args.only.split(",") if p.strip()]
        unknown = set(parts) - set(PARTS)
        if unknown:
            print(f"Bilinmeyen --only değeri: {', '.join(sorted(unknown))}")
            return 2
    with RunLock(settings.lock_file):
        if settings.low_priority:
            lower_process_priority(log)
        log.info("Rewards bot başladı")
        summary = run_once(settings, parts=parts, headless=False if args.visible else None,
                           today=today)
    state.update(last_run=datetime.now().isoformat(timespec="seconds"),
                 last_summary=summary.to_dict())
    if parts is None:
        state["last_success_date"] = today.isoformat()
    write_state(settings.state_file, state)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"Ayar hatası: {exc}", file=sys.stderr)
        notify(f"Ayar hatası: {exc}")
        return 2
    log = setup_logging(settings.log_dir, args.verbose)

    try:
        if args.command == "login":
            return cmd_login(settings, log)
        if args.command == "run":
            return cmd_run(settings, args, log)
        if args.command == "status":
            return cmd_status(settings)
        if args.command == "install-task":
            return install_task(settings)
        if args.command == "uninstall-task":
            return uninstall_task()
    except SessionExpired as exc:
        log.error("%s", exc)
        notify(f"Rewards bot: {exc}")
        return 3
    except AlreadyRunning as exc:
        log.info("%s", exc)
        return 0
    except BrowserStartError as exc:
        log.error("%s", exc)
        notify(f"Rewards bot: {exc}")
        return 4
    except KeyboardInterrupt:
        log.info("Kullanıcı durdurdu.")
        return 130
    except Exception:
        log.exception("Beklenmeyen hata")
        notify("Rewards bot beklenmeyen bir hatayla durdu; ayrıntı logs/rewards_bot.log dosyasında.")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())

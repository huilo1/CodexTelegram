from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import getpass
import json
import logging
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time

from dotenv import dotenv_values
from telethon import errors, functions, utils

from .config import data_dir, load_config, save_config
from .auth import code_login
from .store import Store
from .telegram import make_client, secure_session


@contextmanager
def session_lock():
    with (data_dir() / "service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Stop the background service before changing Telegram authorization") from None
        yield


def import_api(path):
    values = dotenv_values(path)
    api_id, api_hash = values.get("TELEGRAM_API_ID"), values.get("TELEGRAM_API_HASH")
    validate_api(api_id, api_hash)
    config = load_config()
    config.update(api_id=int(api_id), api_hash=api_hash)
    config.setdefault("codex_binary", shutil.which("codex") or "codex")
    save_config(config)
    print("Imported Telegram API ID/hash only. Phone, sessions and other secrets were not copied.")


def validate_api(api_id, api_hash):
    if not api_id or not str(api_id).isdigit() or int(api_id) <= 0 or not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash or ""):
        raise ValueError("Нужны собственные api_id (положительное число) и api_hash (32 hex-символа).")


def configure_api():
    config = load_config()
    if config.get("api_id") and config.get("api_hash"):
        print("Собственные Telegram API-реквизиты уже сохранены; менять их не требуется.")
        return
    print("Откройте https://my.telegram.org → API development tools и создайте СВОЁ приложение.")
    print("Ключи разработчиков плагина не поставляются. QR-вход тоже требует ваши api_id/api_hash.")
    while True:
        api_id = input("Ваш api_id (/cancel — отмена): ").strip()
        if api_id == "/cancel":
            raise ValueError("Настройка отменена.")
        api_hash = getpass.getpass("Ваш api_hash (скрытый ввод): ").strip()
        try:
            validate_api(api_id, api_hash)
        except ValueError as exc:
            print(exc)
            continue
        config.update(api_id=int(api_id), api_hash=api_hash,
                      codex_binary=shutil.which("codex") or "codex")
        save_config(config)
        print("Реквизиты сохранены локально с правами 0600.")
        return


def configure_reporting():
    config = load_config()
    if config.get("reporting_setup"):
        return
    store = Store()
    try:
        if config.get("group_id"):
            print("Сохраняю существующий выбор проектов.")
        else:
            print("В Telegram отправляются статусы и последний публичный ответ Codex.")
            print("Для вопросов Codex читает очищенный снимок кода; выдержки могут попасть в ответ.")
            print("Скрытие секретов эвристическое. Сведения о передаче данных: PRIVACY.md.")
            while True:
                mode = input("Проекты: [1] только выбранные (по умолчанию), [2] все автоматически: ").strip()
                if mode in {"", "1", "2"}:
                    break
                if mode == "/cancel":
                    raise ValueError("Настройка отменена.")
            store.reporting_mode("all" if mode == "2" else "selected")
            if mode != "2":
                print("Подключить проект: python3 scripts/run.py project enable /путь/к/проекту")
        config["reporting_setup"] = True
        save_config(config)
    finally:
        store.close()


async def login(use_qr=False):
    config = load_config()
    client = make_client(config)
    with session_lock():
        try:
            await client.connect()
            if not await client.is_user_authorized():
                while not use_qr:
                    phone = input("Номер СПЕЦИАЛЬНОГО аккаунта Telegram (+...; /qr — QR, /cancel — отмена): ").strip()
                    if phone == "/qr":
                        use_qr = True
                        break
                    if phone == "/cancel":
                        raise ValueError("Вход отменён.")
                    normalized = utils.parse_phone(phone)
                    if phone.startswith("+") and normalized:
                        break
                    print("Введите номер в международном формате с +. Пустой ввод не отправляется в Telegram.")
                if use_qr:
                    from .qr_login import qr_login
                    await qr_login(client)
                else:
                    await code_login(client, phone)
            me = await client.get_me()
            if me.bot:
                raise ValueError("A dedicated user account is required, not a bot")
            if config.get("account_id") and config["account_id"] != me.id:
                raise ValueError("Unexpected account; keep the previous group configuration isolated")
            config["account_id"] = me.id
            config.pop("logged_out", None)
            save_config(config)
            print(f"Авторизация сохранена. Специальный аккаунт: {me.id}, @{me.username or 'без username'}")
        finally:
            secure_session()
            await client.disconnect()


async def setup_group(owner, title):
    config = load_config()
    client = make_client(config)
    with session_lock():
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise ValueError("Run login first")
            me = await client.get_me()
            if me.id != config.get("account_id"):
                raise ValueError("Dedicated account identity mismatch")
            person = await client.get_entity(int(owner) if owner.isdigit() else owner)
            if getattr(person, "bot", True) or person.id == me.id:
                raise ValueError("Owner must be your personal Telegram user, different from the dedicated account")
            if config.get("allowed_user_ids") and config["allowed_user_ids"] != [person.id]:
                raise ValueError("This group is already assigned to another owner")
            if config.get("group_id"):
                group = await client.get_entity(config["group_id"])
            else:
                result = await client(functions.channels.CreateChannelRequest(
                    title=title, about="Отчёты о разработке в Codex. Один проект — одна тема. Вопросы по статусу доступны в темах.",
                    megagroup=True, forum=True))
                group = result.chats[0]
                config.update(group_id=utils.get_peer_id(group), allowed_user_ids=[person.id])
                save_config(config)  # Persist immediately so retries reuse the created group.
                store = Store()
                try:
                    latest = await client.get_messages(group, limit=1)
                    store.set_meta(f'cursor:{config["group_id"]}', latest[0].id if latest else 0)
                finally:
                    store.close()
            if getattr(group, "username", None) or not getattr(group, "forum", False):
                raise ValueError("The configured group must remain a private forum")
            # A leaked link cannot admit a different user; the service approves only the owner.
            invite = await client(functions.messages.ExportChatInviteRequest(
                peer=group, title="Codex reports owner", request_needed=True,
                expire_date=datetime.now(timezone.utc) + timedelta(days=1)))
            config.update(allowed_user_ids=[person.id], invite_link=invite.link)
            save_config(config)
            print("Закрытая группа готова. Вступите по ссылке из личного аккаунта; служба одобрит только ваш ID:")
            print(invite.link)
        finally:
            secure_session()
            await client.disconnect()


async def onboard(use_qr=False):
    configure_api()
    configure_reporting()
    await login(use_qr=use_qr)
    owner = input("@username вашего ЛИЧНОГО аккаунта (получатель отчётов): ").strip()
    if not owner:
        raise ValueError("Personal Telegram username is required")
    await setup_group(owner, "Codex · отчёты")
    if sys.platform == "darwin":
        launchd("install")
    else:
        print("Start the service in another terminal: codex-telegram-reports run")
    print("Откройте ссылку выше личным аккаунтом. Служба одобрит вашу заявку автоматически.")


async def logout():
    client = make_client(load_config())
    with session_lock():
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client.log_out()
            config = load_config()
            config["logged_out"] = True
            save_config(config)
            print("Telegram-сессия отозвана. История отчётов и настройки сохранены локально.")
        finally:
            await client.disconnect()


def test_report():
    config = load_config()
    if not config.get("group_id"):
        raise ValueError("Сначала выполните onboard.")
    path = data_dir() / "setup-check"
    path.mkdir(exist_ok=True)
    store = Store()
    try:
        store.register(str(path), "Проверка установки")
        store.set_project_enabled(str(path), True)
        result = store.report(str(path), "setup", str(time.time_ns()), "Проверка установки", "completed",
                              "Плагин настроен. Это тест доставки. Напишите /status в этой теме, чтобы проверить приём вопросов.")
        print(f"Тест сохранён в очереди (report_id={result['report_id']}). Ожидаю подтверждения Telegram…")
        for _ in range(30):
            pending = store.db.execute("SELECT count(*) FROM outbox WHERE report_id=? AND message_id IS NULL", (result["report_id"],)).fetchone()[0]
            if not pending:
                print("Telegram подтвердил доставку. Проверьте тему «Проверка установки».")
                return
            time.sleep(1)
        raise ValueError("Тест пока в очереди; повторно отправлять его не нужно. Проверьте doctor.")
    finally:
        store.close()


def doctor(as_json=False, check_mcp=False):
    from .diagnostics import diagnose
    result = diagnose(check_mcp)
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Codex Telegram Reports {result['version']}")
        for check in result["checks"]:
            print(f"{'OK' if check['ok'] else 'FAIL'} {check['name']}: {check['detail']}")
        print("Очередь:", json.dumps(result["queue"], ensure_ascii=False))
        print("Доверие четырём hooks проверьте через /hooks в новом разговоре Codex.")
    return 0 if result["ready"] else 1


def launchd(action):
    if sys.platform != "darwin":
        raise ValueError("launchd is available on macOS; use run or the systemd template on Linux")
    label = "org.codex.telegram-reports"
    path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    domain = f"gui/{os.getuid()}"
    if action == "install":
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"Label": label,
                   "ProgramArguments": [str(Path(sys.executable).absolute()), "-m", "codex_telegram_reports.cli", "run"],
                   "WorkingDirectory": str(data_dir()), "RunAtLoad": True, "KeepAlive": True,
                   "ThrottleInterval": 15, "Umask": 0o077,
                   "EnvironmentVariables": {"CODEX_TELEGRAM_REPORTS_HOME": str(data_dir()), "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                   "StandardOutPath": str(data_dir() / "service.log"),
                   "StandardErrorPath": str(data_dir() / "service.log")}
        path.write_bytes(plistlib.dumps(payload))
        path.chmod(0o600)
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
        # bootout can return before launchd releases the old job registration.
        # A bounded retry avoids a transient bootstrap EIO during runtime updates.
        for attempt in range(10):
            result = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True)
            if result.returncode == 0:
                break
            if attempt == 9 or result.returncode != 5:
                raise ValueError(f"launchd could not start the report service (code {result.returncode}); check service status")
            time.sleep(.3)
        print("Background service installed.")
    elif action in {"stop", "uninstall"}:
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
        # Wait for the session writer to exit before a following logout/update.
        for attempt in range(100):
            try:
                with session_lock():
                    break
            except ValueError:
                if attempt == 99:
                    raise ValueError("Служба ещё использует сессию. Остановите foreground-процесс и повторите команду.") from None
                time.sleep(.1)
        if action == "uninstall":
            path.unlink(missing_ok=True)
        print("Служба остановлена." if action == "stop" else "Автозапуск удалён. Данные сохранены.")
    else:
        subprocess.run(["launchctl", "print", f"{domain}/{label}"], check=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Codex project reports through a dedicated Telegram user")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-api", help="Copy only API ID/hash from a local dotenv file")
    imp.add_argument("env_file")
    sub.add_parser("configure-api", help="Enter your own Telegram API ID/hash locally")
    sub.add_parser("login").add_argument("--qr", action="store_true", help="Log in by scanning a QR code with Telegram")
    sub.add_parser("onboard").add_argument("--qr", action="store_true", help="Use QR login before setting up the group")
    group = sub.add_parser("setup-group")
    group.add_argument("--owner", required=True, help="Your PERSONAL Telegram @username or known numeric user id")
    group.add_argument("--title", default="Codex · отчёты")
    for name in ("run", "mcp", "hook", "projects", "logout", "test-report"):
        sub.add_parser(name)
    check = sub.add_parser("doctor")
    check.add_argument("--json", action="store_true")
    check.add_argument("--mcp", action="store_true", help="Perform a local MCP initialize/tools handshake")
    policy = sub.add_parser("reporting")
    policy.add_argument("mode", choices=["all", "selected"])
    project = sub.add_parser("project")
    project.add_argument("action", choices=["enable", "disable", "topic"])
    project.add_argument("path")
    project.add_argument("--name", help="Separate this checkout into a named Telegram topic")
    daemon = sub.add_parser("service")
    daemon.add_argument("action", choices=["install", "stop", "status", "uninstall"])
    args = parser.parse_args()
    try:
        if args.command == "import-api":
            import_api(args.env_file)
        elif args.command == "configure-api":
            configure_api()
        elif args.command == "login":
            asyncio.run(login(use_qr=args.qr))
        elif args.command == "setup-group":
            asyncio.run(setup_group(args.owner, args.title))
        elif args.command == "onboard":
            asyncio.run(onboard(use_qr=args.qr))
        elif args.command == "doctor":
            parser.exit(doctor(args.json, args.mcp))
        elif args.command == "logout":
            asyncio.run(logout())
        elif args.command == "test-report":
            test_report()
        elif args.command == "mcp":
            from .mcp_server import run_mcp
            run_mcp()
        elif args.command == "hook":
            from .hooks import run_hook
            run_hook()
        elif args.command == "run":
            from .service import run_service
            logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
            asyncio.run(run_service())
        elif args.command == "service":
            launchd(args.action)
        elif args.command in {"projects", "project", "reporting"}:
            store = Store()
            try:
                if args.command == "reporting":
                    store.reporting_mode(args.mode)
                elif args.command == "project":
                    if args.action == "topic":
                        if not args.name:
                            raise ValueError("project topic requires --name")
                        store.separate_topic(args.path, args.name)
                    else:
                        store.set_project_enabled(args.path, args.action == "enable")
                print(json.dumps(store.projects(), indent=2, ensure_ascii=False))
            finally:
                store.close()
    except errors.FloodWaitError as exc:
        parser.exit(1, f"Telegram просит подождать {exc.seconds} сек. перед новой попыткой. Мастер можно запустить позднее; сессии сохранены.\n")
    except errors.PhoneNumberFloodError:
        parser.exit(1, "Telegram ограничил запросы кодов для этого номера. Повторите вход позднее.\n")
    except errors.RPCError as exc:
        parser.exit(1, f"Telegram отклонил запрос ({type(exc).__name__}). Сессии сохранены; мастер можно запустить повторно.\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    except EOFError:
        parser.exit(0, "Ввод завершён. Мастер остановлен; его можно запустить повторно.\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

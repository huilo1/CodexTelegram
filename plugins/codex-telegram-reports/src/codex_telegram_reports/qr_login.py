"""QR login shown locally, without an external QR-generation service."""
from __future__ import annotations

import asyncio
from getpass import getpass
import html
import io
import os
from pathlib import Path
import webbrowser

import qrcode
from qrcode.image.svg import SvgPathImage
from telethon import errors

from .auth import LoginCancelled, password_login
from .config import data_dir


class QRDisplay:
    def __init__(self, path: Path | None = None, *, open_browser=webbrowser.open, output=print):
        self.path = path or data_dir() / "login-qr.html"
        self.open_browser, self.output = open_browser, output
        self.opened = False

    def _write(self, title, body, *, refresh=False):
        refresh_tag = '<meta http-equiv="refresh" content="2">' if refresh else ""
        page = f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">{refresh_tag}
<title>Вход в Telegram · Codex Reports</title>
<style>body{{margin:0;background:#edf2f6;color:#172b3a;font:17px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}}main{{background:white;padding:32px;border-radius:20px;max-width:500px;text-align:center;box-shadow:0 10px 40px #172b3a18}}h1{{font-size:24px}}p{{line-height:1.6}}svg{{display:block;width:min(340px,75vw);height:auto;margin:20px auto;background:white}}small{{color:#586b78}}</style>
<main><h1>{html.escape(title)}</h1>{body}</main></html>'''
        temp = self.path.with_suffix(".tmp")
        with open(temp, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
            stream.write(page)
        temp.chmod(0o600)
        temp.replace(self.path)

    def show(self, url):
        image = qrcode.make(url, image_factory=SvgPathImage, border=4)
        buffer = io.BytesIO()
        image.save(buffer)
        svg = buffer.getvalue().decode().split("?>")[-1]
        self._write("Вход специального аккаунта", f'''<p>На телефоне выберите <b>специальный аккаунт</b> Telegram.<br>
Настройки → Устройства → Подключить устройство.</p>{svg}
<p>Отсканируйте QR и подтвердите вход.</p>
<small>QR обновляется автоматически. Для отмены нажмите Ctrl+C в Терминале.</small>''', refresh=True)
        if not self.opened:
            self.opened = True
            self.output(f"QR-код: {self.path}")
            if not self.open_browser(self.path.as_uri()):
                self.output("Откройте этот HTML-файл в браузере вручную.")

    def finish(self, message, *, refresh=False):
        # Remove the live token from disk after success, failure, cancellation or 2FA.
        self._write("Telegram · Codex Reports", f"<p>{html.escape(message)}</p>", refresh=refresh)


async def qr_login(client, *, display=None, secret_input=getpass, output=print, max_refreshes=20):
    display = display or QRDisplay(output=output)
    output("В Telegram на телефоне выберите СПЕЦИАЛЬНЫЙ аккаунт → Настройки → Устройства → Подключить устройство.")
    output("Ожидаю сканирование QR. Номер и код не нужны. Ctrl+C — отмена.")
    waiter = None
    try:
        qr = await client.qr_login()
        for attempt in range(max_refreshes):
            # Register Telethon's UpdateLoginToken handler before revealing the QR.
            waiter = asyncio.create_task(qr.wait())
            await asyncio.sleep(0)
            display.show(qr.url)
            try:
                await waiter
                display.finish("Вход подтверждён. Вернитесь в Терминал, чтобы завершить настройку группы.")
                return
            except errors.SessionPasswordNeededError:
                display.finish("QR принят. Введите пароль двухэтапной аутентификации в Терминале.", refresh=True)
                await password_login(client, secret_input, output)
                display.finish("Вход подтверждён. Вернитесь в Терминал, чтобы завершить настройку группы.")
                return
            except TimeoutError:
                display.finish("Срок QR истёк. Подготавливается новый код.", refresh=True)
                if attempt + 1 < max_refreshes:
                    output("Срок QR истёк — обновляю код.")
                    await qr.recreate()
        raise LoginCancelled("Время ожидания QR истекло. Запустите мастер ещё раз с --qr.")
    except BaseException:
        display.finish("Вход не завершён. Подробности — в Терминале. Мастер можно запустить повторно.")
        raise
    finally:
        if waiter is not None:
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

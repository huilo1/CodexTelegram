import asyncio
from unittest.mock import AsyncMock

import pytest
from telethon import errors

from codex_telegram_reports.auth import LoginCancelled, code_login
from codex_telegram_reports.qr_login import QRDisplay, qr_login


class QR:
    def __init__(self, outcomes):
        self.url = "tg://login?token=test-only-not-a-real-token"
        self.outcomes = iter(outcomes)
        self.registered = False
        self.scanned = asyncio.Event()
        self.refreshes = 0

    async def wait(self):
        self.registered = True
        await self.scanned.wait()
        outcome = next(self.outcomes)
        if outcome:
            raise outcome

    async def recreate(self):
        self.refreshes += 1
        self.url += "new"
        self.registered = False
        self.scanned.clear()


class Display:
    def __init__(self, qr):
        self.qr = qr
        self.urls, self.messages = [], []

    def show(self, url):
        assert self.qr.registered, "Wait handler must be registered before the QR is shown"
        self.urls.append(url)
        self.qr.scanned.set()

    def finish(self, message, **kwargs):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_qr_waits_before_showing_and_logs_in_without_a_phone():
    qr = QR([None]); display = Display(qr)
    client = AsyncMock(); client.qr_login.return_value = qr
    await qr_login(client, display=display, output=lambda _: None)
    assert len(display.urls) == 1
    assert "Вход подтверждён" in display.messages[-1]
    client.send_code_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_qr_is_refreshed_automatically():
    qr = QR([TimeoutError(), None]); display = Display(qr)
    client = AsyncMock(); client.qr_login.return_value = qr
    await qr_login(client, display=display, output=lambda _: None)
    assert qr.refreshes == 1
    assert display.urls[0] != display.urls[1]
    assert "Вход подтверждён" in display.messages[-1]


@pytest.mark.asyncio
async def test_qr_2fa_uses_existing_local_password_prompt():
    qr = QR([errors.SessionPasswordNeededError(request=None)])
    display = Display(qr)
    client = AsyncMock(); client.qr_login.return_value = qr
    await qr_login(client, display=display, secret_input=lambda _: "local-only-password", output=lambda _: None)
    client.sign_in.assert_awaited_once_with(password="local-only-password")
    assert "local-only-password" not in str(display.messages)


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_clears_qr():
    qr = QR([TimeoutError()]); display = Display(qr)
    client = AsyncMock(); client.qr_login.return_value = qr
    with pytest.raises(LoginCancelled):
        await qr_login(client, display=display, output=lambda _: None, max_refreshes=1)
    assert qr.refreshes == 0
    assert "не завершён" in display.messages[-1]


@pytest.mark.asyncio
async def test_code_login_can_switch_to_qr(monkeypatch):
    from telethon import types
    switch = AsyncMock()
    monkeypatch.setattr("codex_telegram_reports.qr_login.qr_login", switch)
    client = AsyncMock()
    client.send_code_request.return_value = types.auth.SentCode(types.auth.SentCodeTypeApp(5), "test-hash")
    await code_login(client, "+15550000000", secret_input=lambda _: "/qr", output=lambda _: None)
    switch.assert_awaited_once()
    client.sign_in.assert_not_awaited()


def test_qr_page_is_local_private_refreshes_and_clears_token(tmp_path):
    opened, output = [], []
    page = tmp_path / "login-qr.html"
    display = QRDisplay(page, open_browser=lambda url: opened.append(url) or True, output=output.append)
    display.show("tg://login?token=test-only-not-a-real-token")
    initial = page.read_text()
    assert "<svg" in initial and 'http-equiv="refresh"' in initial
    assert "test-only-not-a-real-token" not in initial
    assert page.stat().st_mode & 0o777 == 0o600
    display.show("tg://login?token=a-different-test-token")
    assert page.read_text() != initial
    assert len(opened) == 1
    display.finish("Вход подтверждён")
    assert "<svg" not in page.read_text()
    assert "http-equiv=\"refresh\"" not in page.read_text()

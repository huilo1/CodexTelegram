from unittest.mock import AsyncMock

import pytest
from telethon import errors, functions, types

from codex_telegram_reports.auth import LoginCancelled, code_login


def sent(code_hash="first", timeout=0, next_type=True, sms=False):
    return types.auth.SentCode(
        type=types.auth.SentCodeTypeSms(5) if sms else types.auth.SentCodeTypeApp(5),
        phone_code_hash=code_hash, timeout=timeout,
        next_type=types.auth.CodeTypeSms() if next_type else None)


class Client:
    def __init__(self, initial=None):
        self.send_code_request = AsyncMock(return_value=initial or sent())
        self.sign_in = AsyncMock()
        self.requests = []
        self.resend = sent("second", sms=True)

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(self.resend, Exception):
            raise self.resend
        return self.resend


async def run(client, inputs, **kwargs):
    values, output = iter(inputs), []
    await code_login(client, "+15550000000", secret_input=lambda _: next(values), output=output.append, **kwargs)
    return "\n".join(output)


@pytest.mark.asyncio
async def test_empty_code_never_triggers_sign_in_or_hidden_resend():
    client = Client()
    output = await run(client, ["", " ", "12345"])
    client.send_code_request.assert_awaited_once()
    client.sign_in.assert_awaited_once_with("+15550000000", "12345", phone_code_hash="first")
    assert not client.requests
    assert "служебный чат" in output and "Код не введён" in output
    assert "12345" not in output


@pytest.mark.asyncio
async def test_invalid_code_can_be_corrected_without_resending():
    client = Client()
    client.sign_in.side_effect = [errors.PhoneCodeInvalidError(request=None), None]
    output = await run(client, ["11111", "22222"])
    assert client.sign_in.await_count == 2
    client.send_code_request.assert_awaited_once()
    assert "не принял код" in output


@pytest.mark.asyncio
async def test_resend_uses_new_hash_and_shows_new_delivery_type():
    client = Client()
    output = await run(client, ["/resend", "12345"])
    assert isinstance(client.requests[0], functions.auth.ResendCodeRequest)
    assert client.requests[0].phone_code_hash == "first"
    client.sign_in.assert_awaited_once_with("+15550000000", "12345", phone_code_hash="second")
    assert "по SMS" in output


@pytest.mark.asyncio
async def test_resend_respects_server_timeout():
    client = Client(sent(timeout=60))
    output = await run(client, ["/resend", "12345"], now=lambda: 0)
    assert not client.requests
    assert "через 60 сек" in output


@pytest.mark.asyncio
async def test_resend_is_not_promised_when_server_does_not_offer_it():
    client = Client(sent(next_type=False))
    output = await run(client, ["/resend", "12345"])
    assert not client.requests
    assert "не предложил" in output


@pytest.mark.asyncio
async def test_expired_code_allows_explicit_fresh_request():
    client = Client()
    client.send_code_request.side_effect = [sent(), sent("fresh")]
    client.sign_in.side_effect = [errors.PhoneCodeExpiredError(request=None), None]
    output = await run(client, ["11111", "22222", "/resend", "33333"])
    assert client.send_code_request.await_count == 2
    assert client.sign_in.await_count == 2
    assert client.sign_in.await_args.kwargs["phone_code_hash"] == "fresh"
    assert "истёк" in output


@pytest.mark.asyncio
async def test_2fa_empty_and_incorrect_password_can_be_retried():
    client = Client()
    client.sign_in.side_effect = [errors.SessionPasswordNeededError(request=None), errors.PasswordHashInvalidError(request=None), None]
    output = await run(client, ["12345", "", "bad password", "right password"])
    assert client.sign_in.await_count == 3
    assert client.sign_in.await_args.kwargs == {"password": "right password"}
    assert "Пароль не введён" in output
    assert "right password" not in output and "bad password" not in output


@pytest.mark.asyncio
async def test_resend_flood_wait_does_not_crash_or_retry_automatically():
    client = Client()
    client.resend = errors.FloodWaitError(request=None, capture=60)
    output = await run(client, ["/resend", "/resend", "12345"], now=lambda: 0)
    assert len(client.requests) == 1
    assert "Подождите 60 сек" in output


@pytest.mark.asyncio
async def test_cancel_does_not_try_to_sign_in():
    client = Client()
    with pytest.raises(LoginCancelled):
        await run(client, ["/cancel"])
    client.sign_in.assert_not_awaited()

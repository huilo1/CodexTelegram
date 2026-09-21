"""Interactive Telegram login; codes and passwords never leave local prompts."""
from __future__ import annotations

from getpass import getpass
import math
import time

from telethon import errors, functions


class LoginCancelled(ValueError):
    pass


def describe_delivery(sent) -> str:
    kind = type(sent.type).__name__
    messages = {
        "SentCodeTypeApp": "Telegram отправил код в служебный чат «Telegram» в уже открытых сессиях этого аккаунта. Проверьте приложение на телефоне или компьютере; это не SMS.",
        "SentCodeTypeSms": "Telegram отправил код по SMS на указанный номер.",
        "SentCodeTypeCall": "Telegram отправляет код голосовым звонком на указанный номер.",
        "SentCodeTypeFlashCall": "Telegram использует короткий звонок. Кодом служит номер входящего звонка.",
        "SentCodeTypeMissedCall": "Telegram использует пропущенный звонок. Введите последние цифры номера входящего звонка.",
        "SentCodeTypeEmailCode": "Telegram отправил код на настроенную в аккаунте почту для входа.",
        "SentCodeTypeSmsWord": "Telegram отправил SMS: введите слово из сообщения.",
        "SentCodeTypeSmsPhrase": "Telegram отправил SMS: введите фразу из сообщения.",
    }
    if kind not in messages:
        raise ValueError(f"Telegram запросил способ входа {kind}, который этот мастер пока не поддерживает. Используйте официальный Telegram для проверки настроек входа.")
    return messages[kind]


async def password_login(client, secret_input, output):
    while True:
        password = secret_input("Пароль двухэтапной аутентификации (/cancel — отмена): ")
        if password == "/cancel":
            raise LoginCancelled("Вход отменён. Существующие сессии не изменены.")
        if not password:
            output("Пароль не введён. Попробуйте ещё раз или введите /cancel.")
            continue
        try:
            await client.sign_in(password=password)
            return
        except errors.PasswordHashInvalidError:
            output("Неверный пароль двухэтапной аутентификации. Повторите ввод.")


async def code_login(client, phone, *, secret_input=getpass, output=print, now=time.monotonic):
    try:
        sent = await client.send_code_request(phone)
    except errors.SessionPasswordNeededError:
        await password_login(client, secret_input, output)
        return
    output(describe_delivery(sent))
    output("Ввод скрыт. Введите код; /resend — повторная отправка, /qr — вход по QR, /cancel — отмена.")
    resend_after = now() + (sent.timeout or 0)
    retry_login_after = 0
    expired = False
    resend_available = bool(sent.next_type)
    while True:
        code = secret_input("Код входа, /resend или /qr: ").strip()
        if code == "/cancel":
            raise LoginCancelled("Вход отменён. Существующие сессии не изменены.")
        if code == "/qr":
            from .qr_login import qr_login
            await qr_login(client, secret_input=secret_input, output=output)
            return
        if not code:
            output("Код не введён. Проверьте указанный выше способ доставки или введите /resend.")
            continue
        if code == "/resend":
            delay = math.ceil(resend_after - now())
            if delay > 0:
                output(f"Telegram разрешает повторную отправку через {delay} сек. Затем снова введите /resend.")
                continue
            if not expired and not resend_available:
                output("Telegram не предложил другой способ доставки. Проверьте открытые сессии и служебный чат «Telegram». Принудительно переключить доставку на SMS нельзя.")
                continue
            try:
                if expired:
                    sent = await client.send_code_request(phone)
                else:
                    sent = await client(functions.auth.ResendCodeRequest(phone, sent.phone_code_hash))
                output(describe_delivery(sent))
                resend_after = now() + (sent.timeout or 0)
                resend_available = bool(sent.next_type)
                expired = False
            except errors.FloodWaitError as exc:
                resend_after = now() + exc.seconds
                output(f"Telegram ограничил повторную отправку. Подождите {exc.seconds} сек.")
            except errors.SendCodeUnavailableError:
                resend_available = False
                output("Telegram сейчас не разрешает повторную отправку. Проверьте уже открытые сессии этого аккаунта.")
            except errors.PhoneCodeExpiredError:
                expired = True
                # Telethon's public helper can refresh its own cached expired hash.
                output("Срок запроса истёк. Введите /resend ещё раз для нового запроса.")
            continue
        if code.startswith("/"):
            output("Доступны /resend, /qr и /cancel, либо сам код входа.")
            continue
        if expired:
            output("Предыдущий код уже истёк. Введите /resend для нового запроса.")
            continue
        if now() < retry_login_after:
            output(f"Telegram ограничил попытки входа. Подождите {math.ceil(retry_login_after-now())} сек.")
            continue
        try:
            await client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
            return
        except (errors.PhoneCodeEmptyError, errors.PhoneCodeInvalidError):
            output("Telegram не принял код. Проверьте последний полученный код и повторите ввод.")
        except errors.PhoneCodeExpiredError:
            expired = True
            output("Срок действия кода истёк. Введите /resend, чтобы запросить новый.")
        except errors.SessionPasswordNeededError:
            await password_login(client, secret_input, output)
            return
        except errors.FloodWaitError as exc:
            retry_login_after = now() + exc.seconds
            resend_after = max(resend_after, retry_login_after)
            output(f"Telegram ограничил попытки входа. Подождите {exc.seconds} сек.")

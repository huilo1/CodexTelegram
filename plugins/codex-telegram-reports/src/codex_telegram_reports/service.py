from __future__ import annotations

import asyncio
import fcntl
import logging
import time

from telethon.errors import FloodWaitError

from .config import data_dir, load_config
from .responder import Responder
from .store import LABELS, Store
from .telegram import connect
from .attachments import wants_file, selected_workspace, stage_file
from .compact import compact

log = logging.getLogger(__name__)
TASK_COMMANDS = {"/new", "/run", "/exec", "/cancel", "/stop", "/approve", "/cd", "/resume", "/side"}


class Service:
    def __init__(self, store, transport, responder, config):
        self.store, self.transport, self.responder, self.config = store, transport, responder, config

    async def deliver_one(self):
        delivery = self.store.pending_delivery()
        if not delivery:
            return False
        try:
            project = self.store.project(delivery["project_id"])
            topic = await self.transport.ensure_topic(project)
            if not project["topic_id"] or project.get("topic_name") != project["name"]:
                self.store.bind_topic(project["id"], topic)
            message_id = await self.transport.send(delivery, topic)
            self.store.sent(delivery["id"], message_id)
        except Exception as exc:
            delay = exc.seconds + 1 if isinstance(exc, FloodWaitError) else min(300, 2 ** min(delivery["attempts"]+1, 8))
            self.store.delivery_failed(delivery["id"], type(exc).__name__, delay)
            log.warning("Delivery deferred: %s", type(exc).__name__)
        return True

    async def receive(self):
        chat_id = self.config["group_id"]
        messages = await self.transport.messages_after(self.store.get_meta(f"cursor:{chat_id}", 0))
        self.store.ingest(chat_id, messages, set(self.config["allowed_user_ids"]))
        self.store.set_meta("telegram_last_receive", time.time())
        self.store.set_meta("telegram_receive_error", None)

    async def feedback_one(self):
        feedback = self.store.pending_feedback()
        if not feedback:
            return False
        identity = feedback["question_id"]
        if feedback["sender_id"] not in self.config["allowed_user_ids"] or feedback["chat_id"] != self.config["group_id"]:
            self.store.feedback_unavailable(identity)
            return True
        try:
            # A slow acknowledgement must not block incoming messages or final answers.
            async with asyncio.timeout(5):
                if not feedback["read_done"]:
                    await self.transport.mark_question_read(feedback["message_id"], feedback["topic_id"])
                    self.store.feedback_read(identity)
                desired = feedback["desired"]
                if feedback["reaction_state"] != desired:
                    if not (desired == "cleared" and feedback["reaction_state"] == "new" and feedback["attempts"] == 0):
                        # Retrying an ambiguous result is safe: Telegram replaces our reaction.
                        await self.transport.question_reaction(feedback["message_id"], desired == "shown")
                    self.store.feedback_reaction(identity, desired)
        except Exception as exc:
            kind = type(exc).__name__
            if kind in {"ReactionInvalidError", "ReactionsTooManyError", "ChatReactionsNoneError"}:
                self.store.feedback_reaction(identity, "unavailable")
            elif kind in {"MsgIdInvalidError", "MessageIdInvalidError", "PeerIdInvalidError", "ChannelPrivateError"}:
                self.store.feedback_unavailable(identity)
            else:
                delay = exc.seconds+1 if isinstance(exc, FloodWaitError) else min(300, 2 ** min(feedback["attempts"]+1, 8))
                self.store.feedback_failed(identity, kind, delay)
                log.warning("Question acknowledgement deferred: %s", kind)
        return True

    async def answer_one(self):
        question = self.store.pending_question()
        if not question:
            return False
        # Recheck ACL in case the configuration changed after ingestion.
        if question["sender_id"] not in self.config["allowed_user_ids"]:
            with self.store.db:
                self.store.db.execute("UPDATE questions SET state='ignored' WHERE id=?", (question["id"],))
            return True
        text = question["body"].strip()
        command = text.split(maxsplit=1)[0].lower().split("@")[0]
        context = self.store.context(question)
        attachments = []
        if command in TASK_COMMANDS:
            answer = "Здесь доступны только отчёты и уточнения. Задайте задачу в Codex."
        elif command == "/help":
            answer = "Обсуждайте задачу и код, запрашивайте файлы: «пришли APK» или /file относительный/путь. До 2000 MiB (текст — 8 MiB); ключи и базы исключены. /status — краткий статус, /full — полный текст выбранного отчёта/ответа. Ответ на сообщение выбирает его задачу; без reply — последняя. Разработку запускайте в Codex."
        elif command == "/full":
            answer = self.store.full_text(question)
        elif not context["reports"]:
            answer = "В этой теме пока нет доставленных отчётов. Подробности появятся после первого отчёта Codex."
        elif command == "/status":
            latest = {}
            for report in context["reports"]:
                latest[report["task_id"]] = report
            recent = list(latest.values())[-3:]
            answer = "Последние сведения (по отчётам):\n\n" + "\n\n".join(f'{r["title"]} · {LABELS[r["state"]]}\n{compact(r["summary"], 700)}' for r in recent)
            if len(latest) > 3:
                answer += "\n\nДля остальных задач ответьте на их отчёт."
        else:
            try:
                if command == "/file":
                    parts = text.split(maxsplit=1)
                    result = {"text": "", "files": [parts[1].strip().strip('"')] if len(parts) == 2 else []}
                    if not result["files"]:
                        result["text"] = "Укажите путь: /file относительный/путь/к/файлу"
                else:
                    result = await self.responder.answer(context, text)
                answer = result if isinstance(result, str) else result["text"]
                files = result.get("files", []) if isinstance(result, dict) and wants_file(text) else []
                if len(files) > 3:
                    raise ValueError("Можно запросить до трёх файлов за раз.")
                if files:
                    root = selected_workspace(context)
                    for path in dict.fromkeys(files):
                        try:
                            attachments.append(await asyncio.to_thread(stage_file, root, path))
                        except (OSError, ValueError):
                            answer += "\nФайл не отправлен: недоступен, исключён или превышает лимит. Проверьте путь в выбранной рабочей копии."
                    if attachments:
                        answer += "\nВ очереди отправки: " + ", ".join(a["name"] for a in attachments) + "."
                answer = answer.strip() or "Нет файла для отправки. Уточните путь или версию."
            except Exception as exc:
                log.warning("Status answer unavailable: %s", type(exc).__name__)
                answer = "Не удалось получить уточнение от Codex. Последние отчёты сохранены; /status покажет их без обращения к модели. Попробуйте повторить вопрос позже."
        # An explicit request for detail/full text must not be compacted again.
        shorten = command not in {"/full", "/status"} and not any(x in text.lower() for x in ("подроб", "полный", "detail", "full"))
        self.store.answer(question, answer, attachments, shorten=shorten)
        return True

    async def questions_loop(self):
        while True:
            await self.answer_one()
            await asyncio.sleep(1)

    async def feedback_loop(self):
        while True:
            await self.feedback_one()
            await asyncio.sleep(.5)

    async def delivery_loop(self):
        while True:
            await self.deliver_one()
            await asyncio.sleep(1)

    async def sync_topics(self):
        for project in self.store.projects():
            if project["enabled"] and (not project["topic_id"] or project.get("topic_name") != project["name"]):
                topic = await self.transport.ensure_topic(project)
                self.store.bind_topic(project["id"], topic)

    async def run(self):
        worker = asyncio.create_task(self.questions_loop())
        feedback_worker = asyncio.create_task(self.feedback_loop())
        delivery_worker = asyncio.create_task(self.delivery_loop())
        next_invites_check = 0
        try:
            while True:
                if worker.done():
                    await worker
                if feedback_worker.done():
                    await feedback_worker
                if delivery_worker.done():
                    await delivery_worker
                self.store.set_meta("heartbeat", time.time())
                self.config.update(load_config())
                try:
                    if time.monotonic() >= next_invites_check:
                        await self.transport.approve_owner(set(self.config["allowed_user_ids"]))
                        await self.sync_topics()
                        next_invites_check = time.monotonic() + 15
                    await self.receive()
                except Exception as exc:
                    self.store.set_meta("telegram_receive_error", type(exc).__name__)
                    log.warning("Telegram history unavailable: %s", type(exc).__name__)
                    if isinstance(exc, FloodWaitError):
                        await asyncio.sleep(min(exc.seconds + 1, 60))
                await asyncio.sleep(2)
        finally:
            worker.cancel()
            feedback_worker.cancel()
            delivery_worker.cancel()
            await asyncio.gather(worker, feedback_worker, delivery_worker, return_exceptions=True)


async def run_service():
    config = load_config()
    if not config.get("group_id") or not config.get("allowed_user_ids"):
        raise ValueError("Run setup-group with your personal Telegram identity first")
    # Hold one lock for the entire service lifetime: one MTProto session writer.
    with (data_dir() / "service.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Report service is already running") from None
        client, transport = await connect(config)
        store = Store()
        try:
            await Service(store, transport, Responder(config), config).run()
        finally:
            store.set_meta("heartbeat", None)
            store.close()
            await client.disconnect()

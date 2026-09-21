from __future__ import annotations

from telethon import TelegramClient, functions, types, utils

from .config import data_dir
from .attachments import attachment_path
import hashlib
import asyncio
import mimetypes
import os


def make_client(config):
    if not config.get("api_id") or not config.get("api_hash"):
        raise ValueError("Run configure-api (or onboard) before Telegram login")
    return TelegramClient(str(data_dir() / "telegram-user"), int(config["api_id"]), config["api_hash"],
                          flood_sleep_threshold=0, request_retries=2, connection_retries=5)


def secure_session():
    for path in data_dir().glob("telegram-user.session*"):
        path.chmod(0o600)


def incoming(message):
    reply = message.reply_to
    topic = None
    if reply and getattr(reply, "forum_topic", False):
        topic = reply.reply_to_top_id or reply.reply_to_msg_id
    return {"id": message.id, "sender_id": message.sender_id, "out": message.out,
            "text": message.message or "", "topic_id": topic,
            "reply_to": reply.reply_to_msg_id if reply else None}


class Transport:
    def __init__(self, client, group):
        self.client, self.group = client, group

    async def ensure_topic(self, project):
        if project["topic_id"]:
            if project.get("topic_name", project["name"]) != project["name"]:
                await self.client(functions.messages.EditForumTopicRequest(
                    peer=self.group, topic_id=project["topic_id"], title=project["name"]))
            return project["topic_id"]
        # Stable random_id makes a repeat after an ambiguous network result idempotent.
        result = await self.client(functions.messages.CreateForumTopicRequest(
            peer=self.group, title=project["name"], random_id=project["topic_random_id"]))
        for update in result.updates:
            msg = getattr(update, "message", None)
            if msg and isinstance(getattr(msg, "action", None), types.MessageActionTopicCreate):
                return msg.id
            if isinstance(update, types.UpdateMessageID) and update.random_id == project["topic_random_id"]:
                return update.id
        raise RuntimeError("Telegram did not return the forum topic id")

    async def send(self, delivery, topic_id):
        reply = types.InputReplyToMessage(reply_to_msg_id=delivery["reply_to"] or topic_id,
                                         top_msg_id=topic_id)
        if delivery.get("file_digest"):
            with attachment_path(delivery["file_digest"]).open("rb") as stream:
                digest = await asyncio.to_thread(hashlib.file_digest, stream, "sha256")
                if os.fstat(stream.fileno()).st_size != delivery["file_size"] or digest.hexdigest() != delivery["file_digest"]:
                    raise ValueError("Attachment integrity check failed")
                stream.seek(0)
                uploaded = await self.client.upload_file(stream, file_name=delivery["file_name"],
                    file_size=delivery["file_size"], part_size_kb=512)
            media = types.InputMediaUploadedDocument(file=uploaded,
                mime_type=mimetypes.guess_type(delivery["file_name"])[0] or "application/octet-stream",
                attributes=[types.DocumentAttributeFilename(file_name=delivery["file_name"])], force_file=True)
            result = await self.client(functions.messages.SendMediaRequest(
                peer=self.group, media=media, message=delivery["body"], random_id=delivery["random_id"], reply_to=reply))
        else:
            result = await self.client(functions.messages.SendMessageRequest(
                peer=self.group, message=delivery["body"], random_id=delivery["random_id"],
                reply_to=reply, no_webpage=True))
        if isinstance(result, types.UpdateShortSentMessage):
            return result.id
        for update in getattr(result, "updates", []):
            if isinstance(update, types.UpdateMessageID) and update.random_id == delivery["random_id"]:
                return update.id
            msg = getattr(update, "message", None)
            if msg and getattr(msg, "out", False) and getattr(msg, "message", None) == delivery["body"]:
                return msg.id
        raise RuntimeError("Telegram did not confirm the message id")

    async def messages_after(self, cursor):
        return [incoming(m) async for m in self.client.iter_messages(self.group, min_id=cursor, reverse=True, limit=100)]

    async def mark_question_read(self, message_id, topic_id):
        # Forum topics are message threads. Don't mark unrelated topics as read.
        if topic_id and topic_id != 1:
            await self.client(functions.messages.ReadDiscussionRequest(
                peer=self.group, msg_id=topic_id, read_max_id=message_id))
        else:
            await self.client(functions.channels.ReadHistoryRequest(channel=self.group, max_id=message_id))

    async def question_reaction(self, message_id, pending):
        await self.client(functions.messages.SendReactionRequest(
            peer=self.group, msg_id=message_id,
            reaction=[types.ReactionEmoji(emoticon="👀")] if pending else [], big=False))

    async def approve_owner(self, allowed_users):
        requests = await self.client(functions.messages.GetChatInviteImportersRequest(
            peer=self.group, requested=True, offset_date=None, offset_user=types.InputUserEmpty(), limit=100))
        for request in requests.importers:
            if request.user_id in allowed_users:
                person = next(u for u in requests.users if u.id == request.user_id)
                await self.client(functions.messages.HideChatJoinRequestRequest(peer=self.group, user_id=person, approved=True))


async def connect(config):
    client = make_client(config)
    await client.connect()
    secure_session()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise ValueError("Telegram login is required: codex-telegram-reports login")
    me = await client.get_me()
    if not config.get("account_id") or me.id != config["account_id"] or me.bot:
        await client.disconnect()
        raise ValueError("The authorized account differs from the dedicated account")
    try:
        group = await client.get_entity(config["group_id"])
        if not getattr(group, "forum", False) or not getattr(group, "megagroup", False):
            raise ValueError("Configured group is not a Telegram forum")
        if getattr(group, "username", None):
            raise ValueError("Reports require a private group")
        if not (getattr(group, "creator", False) or getattr(getattr(group, "admin_rights", None), "manage_topics", False)):
            raise ValueError("Dedicated account needs Manage Topics rights")
        if utils.get_peer_id(group) != config["group_id"]:
            raise ValueError("Group identity mismatch")
        return client, Transport(client, group)
    except BaseException:
        await client.disconnect()
        raise

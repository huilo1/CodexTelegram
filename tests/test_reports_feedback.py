import asyncio
from types import SimpleNamespace

import pytest
from telethon import functions, types
from telethon.errors import FloodWaitError, ReactionInvalidError

from codex_telegram_reports.service import Service
from codex_telegram_reports.store import Store
from codex_telegram_reports.telegram import Transport


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path/"state.db")
    s.reporting_mode("all")
    report = s.report(str(tmp_path), "thread", "task", "Test", "progress", "Context")
    s.bind_topic(report["project_id"], 50)
    s.sent(s.pending_delivery()["id"], 100)
    yield s
    s.close()


def ingest(store, message_id=101, sender=7, topic=50):
    store.ingest(-100123, [{"id": message_id, "sender_id": sender, "topic_id": topic, "text": "How?", "reply_to": 100}], {7})


class FeedbackTransport:
    def __init__(self):
        self.read = []
        self.reactions = []
        self.error = None

    async def mark_question_read(self, message_id, topic_id):
        self.read.append((message_id, topic_id))

    async def question_reaction(self, message_id, pending):
        if self.error:
            raise self.error
        self.reactions.append((message_id, pending))


def service(store, transport, responder=None):
    return Service(store, transport, responder, {"group_id": -100123, "allowed_user_ids": [7]})


@pytest.mark.asyncio
async def test_acknowledgement_persists_until_entire_answer_is_delivered(store):
    ingest(store)
    transport = FeedbackTransport()
    worker = service(store, transport)
    await worker.feedback_one()
    assert transport.read == [(101, 50)]
    assert transport.reactions == [(101, True)]
    assert not await worker.feedback_one()
    store.answer(store.pending_question(), "x"*4000)  # two outgoing parts
    store.sent(store.pending_delivery()["id"], 102)
    assert not await worker.feedback_one()
    store.sent(store.pending_delivery()["id"], 103)
    await worker.feedback_one()
    assert transport.reactions == [(101, True), (101, False)]
    assert transport.read == [(101, 50)]
    assert store.pending_feedback() is None


@pytest.mark.asyncio
async def test_second_question_acknowledged_while_first_model_answer_waits(store):
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowResponder:
        async def answer(self, *args):
            entered.set()
            await release.wait()
            return "Done"
    ingest(store)
    transport = FeedbackTransport()
    worker = service(store, transport, SlowResponder())
    task = asyncio.create_task(worker.answer_one())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await worker.feedback_one()
        ingest(store, message_id=102)
        await worker.feedback_one()
        assert not task.done()
        assert transport.reactions == [(101, True), (102, True)]
    finally:
        release.set()
        await task


def test_duplicate_unauthorized_and_unknown_topic_do_not_create_receipts(store):
    ingest(store, sender=8)
    ingest(store, topic=999)
    assert store.pending_feedback() is None
    ingest(store)
    ingest(store)
    assert store.db.execute("SELECT count(*) FROM question_feedback").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_read_ack_survives_reaction_failure_and_restart(store, tmp_path):
    ingest(store)
    transport = FeedbackTransport()
    transport.error = ConnectionError("lost reaction acknowledgement")
    await service(store, transport).feedback_one()
    assert store.pending_feedback() is None  # durable backoff
    reopened = Store(tmp_path/"state.db")
    try:
        with reopened.db:
            reopened.db.execute("UPDATE question_feedback SET retry_at=0")
        transport.error = None
        await service(reopened, transport).feedback_one()
        assert transport.read == [(101, 50)]
        assert transport.reactions == [(101, True)]
        assert reopened.pending_feedback() is None
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_disabled_reactions_keep_read_receipt_and_do_not_block_answer(store):
    ingest(store)
    transport = FeedbackTransport()
    transport.error = ReactionInvalidError(None)
    await service(store, transport).feedback_one()
    assert transport.read == [(101, 50)]
    assert store.pending_feedback() is None
    assert store.pending_question() is not None


@pytest.mark.asyncio
async def test_flood_wait_is_respected_without_sleeping_in_delivery_loop(store):
    ingest(store)
    transport = FeedbackTransport()
    transport.error = FloodWaitError(None, capture=30)
    await service(store, transport).feedback_one()
    row = store.db.execute("SELECT * FROM question_feedback").fetchone()
    assert row["attempts"] == 1 and row["last_error"] == "FloodWaitError"
    assert store.pending_feedback() is None
    assert store.pending_question() is not None


@pytest.mark.asyncio
async def test_no_pending_reaction_when_answer_already_arrived(store):
    ingest(store)
    store.answer(store.pending_question(), "Fast answer")
    store.sent(store.pending_delivery()["id"], 102)
    transport = FeedbackTransport()
    await service(store, transport).feedback_one()
    assert transport.read == [(101, 50)]
    assert transport.reactions == []
    assert store.pending_feedback() is None


@pytest.mark.asyncio
async def test_clear_ambiguous_reaction_after_answer_even_without_local_ack(store):
    ingest(store)
    q = store.pending_question()
    store.feedback_read(q["id"])
    store.feedback_failed(q["id"], "TimeoutError", 0)
    store.answer(q, "Ready")
    store.sent(store.pending_delivery()["id"], 102)
    transport = FeedbackTransport()
    await service(store, transport).feedback_one()
    assert transport.reactions == [(101, False)]


@pytest.mark.asyncio
async def test_transport_read_and_reaction_schema_and_topic_scope():
    calls = []
    async def client(request):
        calls.append(request)
        return True
    transport = Transport(client, types.InputPeerChannel(123, 456))
    await transport.mark_question_read(102, 50)
    assert isinstance(calls[-1], functions.messages.ReadDiscussionRequest)
    assert calls[-1].msg_id == 50 and calls[-1].read_max_id == 102
    await transport.mark_question_read(103, 1)
    assert isinstance(calls[-1], functions.channels.ReadHistoryRequest)
    await transport.question_reaction(102, True)
    assert calls[-1].msg_id == 102 and calls[-1].reaction[0].emoticon == "👀"
    await transport.question_reaction(102, False)
    assert calls[-1].reaction == []

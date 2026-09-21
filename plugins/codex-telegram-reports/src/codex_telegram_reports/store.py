from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from .config import data_dir, project_root, redact, split_text, workspace_root
from .compact import compact

STATES = {"started", "progress", "blocked", "completed", "failed", "interrupted"}
LABELS = {"started": "Начало", "progress": "Прогресс", "blocked": "Нужно внимание", "completed": "Итог", "failed": "Ошибка", "interrupted": "Остановлено"}


def random_id() -> int:
    return secrets.randbits(63) or 1


class Store:
    def __init__(self, path: Path | None = None):
        path = path or data_dir() / "reports.sqlite3"
        self.db = sqlite3.connect(path, timeout=10)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS projects(
          id TEXT PRIMARY KEY, root TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          topic_id INTEGER UNIQUE, topic_random_id INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS reports(
          id INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, project_id TEXT NOT NULL REFERENCES projects(id),
          thread_id TEXT NOT NULL, task_id TEXT NOT NULL, title TEXT NOT NULL, state TEXT NOT NULL,
          summary TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(
          id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), report_id INTEGER REFERENCES reports(id),
          question_id INTEGER, body TEXT NOT NULL, random_id INTEGER UNIQUE NOT NULL,
          reply_to INTEGER, message_id INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
          retry_at REAL NOT NULL DEFAULT 0, last_error TEXT);
        CREATE TABLE IF NOT EXISTS questions(
          id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
          project_id TEXT NOT NULL REFERENCES projects(id), sender_id INTEGER NOT NULL,
          body TEXT NOT NULL, reply_to INTEGER, state TEXT NOT NULL DEFAULT 'pending',
          answer TEXT, created REAL NOT NULL, UNIQUE(chat_id,message_id));
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_contexts(
          project_id TEXT NOT NULL REFERENCES projects(id), thread_id TEXT NOT NULL,
          task_id TEXT NOT NULL, workspace TEXT NOT NULL, details TEXT NOT NULL, updated REAL NOT NULL,
          PRIMARY KEY(project_id,thread_id,task_id));
        CREATE TABLE IF NOT EXISTS question_feedback(
          question_id INTEGER PRIMARY KEY REFERENCES questions(id), read_done INTEGER NOT NULL DEFAULT 0,
          reaction_state TEXT NOT NULL DEFAULT 'new', attempts INTEGER NOT NULL DEFAULT 0,
          retry_at REAL NOT NULL DEFAULT 0, last_error TEXT);
        CREATE TABLE IF NOT EXISTS workspace_topics(
          workspace TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attachments(
          id INTEGER PRIMARY KEY, digest TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL);
        """)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for table, column, kind in (("reports", "workspace", "TEXT"),
                                         ("questions", "context_report_id", "INTEGER"),
                                         ("outbox", "attachment_id", "INTEGER REFERENCES attachments(id)"),
                                         ("projects", "repository_root", "TEXT"),
                                         ("projects", "topic_name", "TEXT"),
                                         ("projects", "opted", "INTEGER")):
                if column not in {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
                    if table == "projects" and column == "opted":
                        self.db.execute("UPDATE projects SET opted=0 WHERE enabled=0")
                    if column == "topic_name":
                        self.db.execute("UPDATE projects SET topic_name=name WHERE topic_id IS NOT NULL")
            # Preserve the original owner's all-project setup; new installs start opt-in.
            if self.get_meta("reporting_mode") is None:
                mode = "all" if self.db.execute("SELECT 1 FROM projects LIMIT 1").fetchone() else "selected"
                self.db.execute("INSERT INTO meta VALUES('reporting_mode',?)", (json.dumps(mode),))
            # Recover unfinished questions on upgrade, without reacting to old completed conversations.
            self.db.execute("""INSERT OR IGNORE INTO question_feedback(question_id)
                SELECT q.id FROM questions q WHERE q.state='pending' OR EXISTS(
                  SELECT 1 FROM outbox o WHERE o.question_id=q.id AND o.message_id IS NULL)""")

    def close(self):
        self.db.close()

    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        with self.db:
            self.db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def register(self, cwd: str, name: str | None = None) -> dict:
        repository = project_root(cwd)
        actual = Path(cwd).expanduser().resolve(strict=True)
        routes = self.db.execute("SELECT * FROM workspace_topics ORDER BY length(workspace) DESC").fetchall()
        route = next((r for r in routes if actual.is_relative_to(r["workspace"])), None)
        root = route["workspace"] if route else repository
        identity = hashlib.sha256(root.encode()).hexdigest()[:16]
        title = redact(name or (route["name"] if route else Path(root).name))[:100]
        if not title.strip():
            raise ValueError("Project name cannot be empty")
        with self.db:
            enabled = int(self.get_meta("reporting_mode", "selected") == "all")
            # A separated worktree inherits explicit consent from its repository.
            parent = self.db.execute("SELECT enabled,opted FROM projects WHERE root=?", (repository,)).fetchone()
            opted = parent["opted"] if route and parent else None
            if route and parent:
                enabled = parent["enabled"]
            self.db.execute("INSERT OR IGNORE INTO projects(id,root,name,topic_random_id,enabled,repository_root,opted) VALUES(?,?,?,?,?,?,?)", (identity, root, title, random_id(), enabled, repository, opted))
        return dict(self.db.execute("SELECT * FROM projects WHERE root=?", (root,)).fetchone())

    def separate_topic(self, cwd, name):
        workspace = workspace_root(cwd)
        title = redact(name).strip()[:100]
        if not title:
            raise ValueError("Topic name is required")
        with self.db:
            self.db.execute("INSERT INTO workspace_topics VALUES(?,?) ON CONFLICT(workspace) DO UPDATE SET name=excluded.name", (workspace, title))
        project = self.register(workspace)
        with self.db:
            self.db.execute("UPDATE projects SET name=?,repository_root=? WHERE id=?", (title, project_root(workspace), project["id"]))
        return self.project(project["id"])

    def reporting_mode(self, mode):
        if mode not in {"all", "selected"}:
            raise ValueError("Reporting mode must be all or selected")
        with self.db:
            self.db.execute("INSERT INTO meta VALUES('reporting_mode',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(mode),))
            self.db.execute("UPDATE projects SET enabled=COALESCE(opted,?)", (int(mode == "all"),))

    def set_project_enabled(self, cwd, enabled):
        project = self.register(cwd)
        with self.db:
            self.db.execute("UPDATE projects SET enabled=?,opted=? WHERE id=?", (int(enabled), int(enabled), project["id"]))
        return self.project(project["id"])

    def projects(self):
        return [dict(x) for x in self.db.execute("SELECT * FROM projects ORDER BY name")]

    def project(self, identity):
        row = self.db.execute("SELECT * FROM projects WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("Unknown project")
        return dict(row)

    def topic_project(self, topic_id):
        row = self.db.execute("SELECT * FROM projects WHERE topic_id=? AND enabled=1", (topic_id,)).fetchone()
        return dict(row) if row else None

    def bind_topic(self, identity, topic_id):
        with self.db:
            self.db.execute("UPDATE projects SET topic_id=?,topic_name=name WHERE id=?", (topic_id, identity))

    def report(self, cwd, thread_id, task_id, title, state, summary, event_key=None, *, attachments=()):
        if state not in STATES:
            raise ValueError("Unknown report state")
        if not all(isinstance(x, str) and x.strip() for x in (thread_id, task_id, title, summary)):
            raise ValueError("thread_id, task_id, title and summary are required")
        if len(summary) > 24000:
            raise ValueError("Summary exceeds 24000 characters")
        project = self.register(cwd)
        if not project["enabled"]:
            return {"queued": False, "reason": "project disabled"}
        title, summary = redact(title)[:160], redact(summary)
        # Caller keys are scoped to a project/thread/task, never global.
        key = json.dumps([project["id"], thread_id, task_id, event_key or [state, title, summary]], ensure_ascii=False)
        text = f'{LABELS[state]} · {project["name"]}\n{title}\n\n{compact(summary)}'
        with self.db:
            row = self.db.execute("SELECT id FROM reports WHERE event_key=?", (key,)).fetchone()
            if row:
                return {"queued": True, "duplicate": True, "report_id": row[0]}
            cur = self.db.execute("INSERT INTO reports(event_key,project_id,thread_id,task_id,title,state,summary,created,workspace) VALUES(?,?,?,?,?,?,?,?,?)",
                                  (key, project["id"], thread_id, task_id, title, state, summary, time.time(), workspace_root(cwd)))
            report_id = cur.lastrowid
            for body in split_text(text):
                self.db.execute("INSERT INTO outbox(project_id,report_id,body,random_id) VALUES(?,?,?,?)", (project["id"], report_id, body, random_id()))
            for attachment in attachments:
                self._attach(project["id"], attachment, report_id=report_id)
        return {"queued": True, "report_id": report_id, "project_id": project["id"]}

    def task_context(self, cwd, thread_id, task_id, details):
        """Explicit, report-safe task notes; never import transcripts or raw prompts."""
        if not all(isinstance(x, str) and x.strip() for x in (thread_id, task_id)):
            raise ValueError("Thread and task are required")
        fields = {"goal", "plan", "decisions", "checks", "next_steps"}
        if not details or set(details) - fields or any(not isinstance(v, str) for v in details.values()):
            raise ValueError("Task context must contain supported text fields")
        if sum(len(v) for v in details.values()) > 16000:
            raise ValueError("Task context exceeds 16000 characters")
        project = self.register(cwd)
        if not project["enabled"]:
            return {"saved": False, "reason": "project disabled"}
        with self.db:
            self.db.execute("""INSERT INTO task_contexts VALUES(?,?,?,?,?,?)
                ON CONFLICT(project_id,thread_id,task_id) DO UPDATE SET
                workspace=excluded.workspace,details=excluded.details,updated=excluded.updated""",
                (project["id"], thread_id, task_id, workspace_root(cwd),
                 json.dumps({k:redact(v) for k,v in details.items()}, ensure_ascii=False), time.time()))
        return {"saved": True, "project_id": project["id"]}

    def _question_report(self, project_id, chat_id, reply_to):
        if reply_to:
            row = self.db.execute("""SELECT COALESCE(o.report_id,q.context_report_id) FROM outbox o
                LEFT JOIN questions q ON q.id=o.question_id
                WHERE o.project_id=? AND o.message_id=?""", (project_id, reply_to)).fetchone()
            if row and row[0]:
                return row[0]
            row = self.db.execute("SELECT context_report_id FROM questions WHERE project_id=? AND chat_id=? AND message_id=?",
                                  (project_id, chat_id, reply_to)).fetchone()
            if row and row[0]:
                return row[0]
        row = self.db.execute("""SELECT r.id FROM reports r WHERE r.project_id=?
            AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.report_id=r.id AND o.message_id IS NULL)
            ORDER BY r.id DESC LIMIT 1""", (project_id,)).fetchone()
        return row[0] if row else None

    def pending_delivery(self):
        row = self.db.execute("""SELECT o.*,a.digest AS file_digest,a.name AS file_name,a.size AS file_size
          FROM outbox o JOIN projects p ON p.id=o.project_id LEFT JOIN attachments a ON a.id=o.attachment_id
          WHERE o.message_id IS NULL AND o.retry_at<=? AND p.enabled=1
          AND NOT EXISTS(SELECT 1 FROM outbox prior WHERE prior.project_id=o.project_id
            AND prior.id<o.id AND prior.message_id IS NULL) ORDER BY o.id LIMIT 1""", (time.time(),)).fetchone()
        return dict(row) if row else None

    def sent(self, identity, message_id):
        with self.db:
            self.db.execute("UPDATE outbox SET message_id=?,last_error=NULL WHERE id=?", (message_id, identity))

    def delivery_failed(self, identity, error, delay):
        with self.db:
            self.db.execute("UPDATE outbox SET attempts=attempts+1,retry_at=?,last_error=? WHERE id=?", (time.time()+delay, error[:100], identity))

    def ingest(self, chat_id, messages, allowed_users):
        """Advance the cursor and persist accepted questions in one transaction."""
        key = f"cursor:{chat_id}"
        cursor = self.get_meta(key, 0)
        with self.db:
            for msg in messages:
                cursor = max(cursor, msg["id"])
                if msg.get("out") or msg.get("sender_id") not in allowed_users or not msg.get("text", "").strip():
                    continue
                project = self.topic_project(msg.get("topic_id"))
                if not project:
                    continue
                inserted = self.db.execute("INSERT OR IGNORE INTO questions(chat_id,message_id,project_id,sender_id,body,reply_to,created,context_report_id) VALUES(?,?,?,?,?,?,?,?)",
                                (chat_id, msg["id"], project["id"], msg["sender_id"], redact(msg["text"])[:8000], msg.get("reply_to"), time.time(),
                                 self._question_report(project["id"], chat_id, msg.get("reply_to"))))
                if inserted.rowcount:
                    self.db.execute("INSERT INTO question_feedback(question_id) VALUES(?)", (inserted.lastrowid,))
            self.db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(cursor)))

    def pending_question(self):
        row = self.db.execute("SELECT q.* FROM questions q JOIN projects p ON p.id=q.project_id WHERE q.state='pending' AND p.enabled=1 ORDER BY q.id LIMIT 1").fetchone()
        return dict(row) if row else None

    def pending_feedback(self):
        row = self.db.execute("""WITH feedback AS (
            SELECT f.*,q.message_id,q.sender_id,q.chat_id,p.topic_id,
              CASE WHEN q.state='answered' AND NOT EXISTS(
                SELECT 1 FROM outbox o WHERE o.question_id=q.id AND o.message_id IS NULL)
                THEN 'cleared' ELSE 'shown' END AS desired
            FROM question_feedback f JOIN questions q ON q.id=f.question_id
              JOIN projects p ON p.id=q.project_id
            WHERE q.state!='ignored' AND p.enabled=1 AND f.retry_at<=?)
            SELECT * FROM feedback WHERE read_done=0 OR
              (reaction_state!='unavailable' AND reaction_state!=desired)
            ORDER BY question_id LIMIT 1""", (time.time(),)).fetchone()
        return dict(row) if row else None

    def feedback_read(self, question_id):
        with self.db:
            self.db.execute("UPDATE question_feedback SET read_done=1,last_error=NULL WHERE question_id=?", (question_id,))

    def feedback_reaction(self, question_id, state):
        if state not in {"shown", "cleared", "unavailable"}:
            raise ValueError("Unknown reaction state")
        with self.db:
            self.db.execute("UPDATE question_feedback SET reaction_state=?,attempts=0,retry_at=0,last_error=NULL WHERE question_id=?", (state, question_id))

    def feedback_failed(self, question_id, error, delay):
        with self.db:
            self.db.execute("UPDATE question_feedback SET attempts=attempts+1,retry_at=?,last_error=? WHERE question_id=?",
                            (time.time()+delay, error[:100], question_id))

    def feedback_unavailable(self, question_id):
        """Deleted/inaccessible message: don't keep retrying presentation feedback."""
        with self.db:
            self.db.execute("UPDATE question_feedback SET read_done=1,reaction_state='unavailable',last_error=NULL WHERE question_id=?", (question_id,))

    def context(self, question):
        # Only fully delivered reports are eligible for Telegram Q&A.
        rows = self.db.execute("""SELECT r.* FROM reports r WHERE project_id=?
          AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.report_id=r.id AND o.message_id IS NULL)
          ORDER BY r.id DESC LIMIT 30""", (question["project_id"],)).fetchall()
        identity = question.get("context_report_id") or self._question_report(question["project_id"], question["chat_id"], question.get("reply_to"))
        row = self.db.execute("""SELECT r.* FROM reports r WHERE r.id=? AND r.project_id=?
            AND NOT EXISTS(SELECT 1 FROM outbox o WHERE o.report_id=r.id AND o.message_id IS NULL)""",
            (identity, question["project_id"])).fetchone()
        target = dict(row) if row else None
        history, notes, workspace = [], None, None
        if target:
            history = self.db.execute("""SELECT q.body,q.answer FROM questions q JOIN reports r ON r.id=q.context_report_id
                WHERE q.project_id=? AND q.state='answered' AND r.thread_id=? AND r.task_id=? AND q.id<?
                ORDER BY q.id DESC LIMIT 8""", (question["project_id"], target["thread_id"], target["task_id"], question["id"])).fetchall()
            note = self.db.execute("SELECT * FROM task_contexts WHERE project_id=? AND thread_id=? AND task_id=?",
                                  (question["project_id"], target["thread_id"], target["task_id"])).fetchone()
            if note:
                notes = {"updated": note["updated"], **json.loads(note["details"])}
            workspace = target["workspace"] or (note["workspace"] if note else None)
        safe_fields = ("thread_id", "task_id", "title", "state", "summary", "created")
        reports, remaining = [], 30000
        for row in rows:
            report = {k: row[k] for k in safe_fields}
            report["summary"] = report["summary"][:min(6000, remaining)]
            reports.append(report)
            remaining -= len(report["summary"])
            if remaining <= 0:
                break
        reports.reverse()
        if target:
            target["summary"] = target["summary"][:12000]
        project = self.project(question["project_id"])
        return {"project": project["name"],
                "_workspace": workspace or project["root"], "_project_root": project["repository_root"] or project["root"],
                "workspace_selection": "reported checkout" if workspace else "legacy report: project root, original checkout unknown",
                "task_context": notes,
                "reports": reports,
                "reply_report": {k: target[k] for k in safe_fields} if target else None,
                "previous_questions": [{"body": r["body"][:1000], "answer": r["answer"][:2000]} for r in reversed(history)]}

    def _attach(self, project_id, attachment, *, report_id=None, question_id=None, reply_to=None):
        row = self.db.execute("INSERT INTO attachments(digest,name,size) VALUES(?,?,?)",
                              (attachment["digest"], attachment["name"], attachment["size"]))
        caption = attachment["name"] + (" · типовые секреты скрыты" if attachment.get("sanitized") else "")
        self.db.execute("INSERT INTO outbox(project_id,report_id,question_id,body,random_id,reply_to,attachment_id) VALUES(?,?,?,?,?,?,?)",
                        (project_id, report_id, question_id, caption, random_id(), reply_to, row.lastrowid))

    def send_file(self, cwd, thread_id, task_id, file_path, caption="", event_key=None):
        from .attachments import stage_file
        project = self.register(cwd)
        if not project["enabled"]:
            return {"queued": False, "reason": "project disabled"}
        attachment = stage_file(Path(workspace_root(cwd)), file_path)
        key = "file:" + (event_key or json.dumps([file_path, attachment["digest"], caption]))
        # The report and attachment are committed together; retries reuse the same outbox row.
        return self.report(cwd, thread_id, task_id, "Файл по запросу", "progress",
                           caption or attachment["name"], key, attachments=[attachment])

    def full_text(self, question):
        if question.get("reply_to"):
            row = self.db.execute("""SELECT q.answer FROM outbox o JOIN questions q ON q.id=o.question_id
                WHERE o.project_id=? AND o.message_id=?""", (question["project_id"], question["reply_to"])).fetchone()
            if row:
                return row[0]
        identity = question.get("context_report_id")
        row = self.db.execute("SELECT summary FROM reports WHERE id=? AND project_id=?", (identity, question["project_id"])).fetchone()
        return row[0] if row else "Нет выбранного отчёта. Ответьте командой /full на нужное сообщение."

    def answer(self, question, text, attachments=(), *, shorten=False):
        text = redact(text)[:24000]
        with self.db:
            updated = self.db.execute("UPDATE questions SET state='answered',answer=? WHERE id=? AND state='pending' AND project_id IN (SELECT id FROM projects WHERE enabled=1)", (text, question["id"]))
            if not updated.rowcount:
                return
            for body in split_text(compact(text) if shorten else text):
                self.db.execute("INSERT INTO outbox(project_id,question_id,body,random_id,reply_to) VALUES(?,?,?,?,?)",
                                (question["project_id"], question["id"], body, random_id(), question["message_id"]))
            for attachment in attachments:
                self._attach(question["project_id"], attachment, question_id=question["id"], reply_to=question["message_id"])

    def health(self):
        error = self.db.execute("SELECT last_error FROM outbox WHERE last_error IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        return {"projects": self.db.execute("SELECT count(*) FROM projects").fetchone()[0],
                "reporting_mode": self.get_meta("reporting_mode", "selected"),
                "pending_messages": self.db.execute("SELECT count(*) FROM outbox WHERE message_id IS NULL").fetchone()[0],
                "pending_questions": self.db.execute("SELECT count(*) FROM questions WHERE state='pending'").fetchone()[0],
                "last_service_heartbeat": self.get_meta("heartbeat"),
                "last_delivery_error": error[0] if error else None}

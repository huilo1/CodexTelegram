from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from .config import Settings
from .session_store import ChatSession

ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass
class CodexRunResult:
    thread_id: str | None = None
    messages: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    raw_events: list[dict[str, object]] = field(default_factory=list)
    raw_output: list[str] = field(default_factory=list)

    @property
    def final_text(self) -> str:
        if not self.messages:
            return "Codex finished without a final message."
        return "\n\n".join(self.messages).strip()


class CodexRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(
        self,
        session: ChatSession,
        prompt: str,
        on_progress: ProgressCallback | None = None,
    ) -> CodexRunResult:
        cmd = self._build_command(session)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=session.cwd,
        )
        try:
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()

            result = CodexRunResult(thread_id=session.thread_id)
            while True:
                raw_line = await process.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                result.raw_output.append(line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                result.raw_events.append(event)
                await self._consume_event(result, event, on_progress)

            return_code = await process.wait()
            if return_code != 0:
                details = result.final_text
                raw_output = " | ".join(result.raw_output[-5:])
                raise RuntimeError(
                    f"codex exited with code {return_code}." + (
                        f" Last output: {details}" if details else ""
                    ) + (f" Raw tail: {raw_output}" if raw_output else "")
                )
            return result
        except asyncio.CancelledError:
            await self._terminate_process(process)
            raise
        except Exception:
            await self._terminate_process(process)
            raise

    def _build_command(self, session: ChatSession) -> list[str]:
        base = ["codex", "exec"]
        if self.settings.codex_model:
            base.extend(["--model", self.settings.codex_model])
        if self.settings.codex_profile:
            base.extend(["--profile", self.settings.codex_profile])
        if self.settings.codex_enable_web_search:
            base.append("--search")
        if session.thread_id:
            base.extend(
                [
                    "resume",
                    "--json",
                    "--skip-git-repo-check",
                    session.thread_id,
                    "-",
                ]
            )
            return base
        base.extend(
            [
                "--json",
                "--skip-git-repo-check",
                "--sandbox",
                self.settings.codex_sandbox,
                "--cd",
                session.cwd,
                "-",
            ]
        )
        return base

    async def _consume_event(
        self,
        result: CodexRunResult,
        event: dict[str, object],
        on_progress: ProgressCallback | None,
    ) -> None:
        event_type = str(event.get("type", ""))
        if event_type == "thread.started":
            result.thread_id = str(event.get("thread_id"))
            if on_progress:
                await on_progress("Session started")
            return
        item = event.get("item")
        if not isinstance(item, dict):
            return
        item_type = str(item.get("type", ""))
        if item_type == "agent_message" and event_type == "item.completed":
            text = str(item.get("text", "")).strip()
            if text:
                result.messages.append(text)
                if on_progress and self.settings.codex_progress_updates:
                    await on_progress(text[:3000])
            return
        if item_type == "command_execution":
            command = str(item.get("command", "")).strip()
            if command:
                result.commands.append(command)
                if on_progress and self.settings.codex_progress_updates:
                    await on_progress(f"Running command: `{command}`")

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
            return
        except asyncio.TimeoutError:
            pass
        with contextlib.suppress(ProcessLookupError):
            process.kill()
            await process.wait()

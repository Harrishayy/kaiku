"""Text-mode voice: Kaiku's lines print to stderr, your typed lines are utterances.

Typed shortcuts in text mode (handled by the hub): `start`, `skip`, a number 1-5 (mood), `yes`/`no`.
"""

from __future__ import annotations

import asyncio
import sys
import threading

from .base import ToolHandler, UtteranceHandler, Voice


class TextVoice(Voice):
    name = "text"

    def __init__(self, read_stdin: bool = True):
        self.read_stdin = read_stdin
        self._thread: threading.Thread | None = None

    async def start(self, on_utterance: UtteranceHandler, on_tool: ToolHandler | None = None) -> None:
        if not self.read_stdin or self._thread:
            return
        loop = asyncio.get_running_loop()

        def reader() -> None:  # daemon thread: never blocks shutdown
            for line in sys.stdin:
                line = line.strip()
                if line:
                    asyncio.run_coroutine_threadsafe(on_utterance(line), loop)

        self._thread = threading.Thread(target=reader, name="stdin", daemon=True)
        self._thread.start()
        print("Kaiku text mode: type `start`, `skip`, 1-5, yes/no, or anything to say.", file=sys.stderr, flush=True)

    async def say(self, text: str) -> None:
        print(f"\U0001f916 Kaiku: {text}", file=sys.stderr, flush=True)

    async def send_context(self, text: str) -> None:
        print(f"   \u00b7 context: {text}", file=sys.stderr, flush=True)  # demo: what Live would be told

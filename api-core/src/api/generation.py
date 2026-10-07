"""Background LLM generations, decoupled from the HTTP request lifetime.

Why this exists
---------------
A browser refresh (or a closed tab, or a flaky connection) aborts the
in-flight ``fetch`` — which, when generation was tied to the request,
also killed the generation and left a truncated reply in the DB.

Here the generation runs in its own ``asyncio.Task``. HTTP responses are
only *subscribers* that replay the chunks produced so far and then follow
new ones, so a disconnect no longer affects generation. Stopping is an
explicit action (``GenerationManager.stop``), no longer inferred from a
dropped connection.

Limitation: state lives in this process only. With several uvicorn workers
or instances, move the chunk buffer + stop signal to Redis (or similar).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_SENTINEL = object()


class GenerationAlreadyRunningError(Exception):
    """A generation for this conversation is already in progress."""


@dataclass
class Generation:
    conversation_id: str
    chunks: list[str] = field(default_factory=list)
    finished: bool = False
    stop_requested: bool = False
    stopped: bool = False
    error: str | None = None
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task[None] | None = None

    def text(self) -> str:
        return "".join(self.chunks)


class GenerationManager:
    def __init__(self) -> None:
        self._active: dict[str, Generation] = {}

    # ---- queries -------------------------------------------------------
    def get(self, conversation_id: str) -> Generation | None:
        gen = self._active.get(conversation_id)
        return gen if gen is not None and not gen.finished else None

    def is_active(self, conversation_id: str) -> bool:
        return self.get(conversation_id) is not None

    def active_ids(self) -> list[str]:
        """Conversation ids with a reply being generated right now."""
        return [cid for cid, gen in self._active.items() if not gen.finished]

    # ---- lifecycle -----------------------------------------------------
    def start(
        self,
        conversation_id: str,
        stream: Iterator[str],
        *,
        persist: Callable[[str], None],
        after: Callable[[], Awaitable[None]] | None = None,
    ) -> Generation:
        """Start generating in the background.

        ``stream`` is the advisor's blocking chunk iterator. ``persist``
        saves the final (or stopped/partial) text. ``after`` runs only
        after a clean finish or a user stop with text (e.g. auto-title).
        """
        if self.is_active(conversation_id):
            raise GenerationAlreadyRunningError(conversation_id)
        gen = Generation(conversation_id)
        self._active[conversation_id] = gen
        # Keep a strong reference on the Generation so the task isn't GC'd.
        gen.task = asyncio.create_task(self._run(gen, stream, persist, after))
        return gen

    def stop(self, conversation_id: str) -> bool:
        gen = self.get(conversation_id)
        if gen is None:
            return False
        gen.stop_requested = True
        return True

    # ---- consumption ---------------------------------------------------
    async def subscribe(
        self, gen: Generation, start_index: int = 0
    ) -> AsyncIterator[str]:
        """Yield chunks from ``start_index`` on, until the generation ends.

        Cancelling/closing this iterator (client disconnect) does not
        touch the generation.
        """
        i = start_index
        while True:
            async with gen.cond:
                # Bind i as a default arg: the predicate runs inside wait_for.
                await gen.cond.wait_for(lambda i=i: i < len(gen.chunks) or gen.finished)
                batch = gen.chunks[i:]
                finished = gen.finished
            i += len(batch)
            for piece in batch:
                yield piece
            if finished and not batch:
                return

    # ---- internals -----------------------------------------------------
    async def _run(
        self,
        gen: Generation,
        stream: Iterator[str],
        persist: Callable[[str], None],
        after: Callable[[], Awaitable[None]] | None,
    ) -> None:
        try:
            while not gen.stop_requested:
                piece = await asyncio.to_thread(next, stream, _SENTINEL)
                if piece is _SENTINEL:
                    break
                if not piece:
                    continue
                async with gen.cond:
                    gen.chunks.append(str(piece))
                    gen.cond.notify_all()
            gen.stopped = gen.stop_requested
        except asyncio.CancelledError:
            # Server shutdown: keep whatever we have.
            gen.stopped = True
            raise
        except Exception as e:
            logger.exception(
                "[generation] failed | conversation_id=%s", gen.conversation_id
            )
            gen.error = str(e)
        finally:
            # No thread is inside next() here, so closing is safe. This
            # also closes the upstream HTTP stream to the model provider.
            try:
                stream.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

            try:
                persist(gen.text().strip())
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[generation] persist failed | conversation_id=%s",
                    gen.conversation_id,
                )

            if after is not None and gen.error is None:
                try:
                    await after()
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[generation] after-hook failed | conversation_id=%s",
                        gen.conversation_id,
                    )

            self._active.pop(gen.conversation_id, None)
            async with gen.cond:
                gen.finished = True
                gen.cond.notify_all()


generation_manager = GenerationManager()

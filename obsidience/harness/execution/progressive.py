"""Private progression of one read-only observation within its admitted Agent turn.

The evidence owner supplies a finite sequence over one frozen snapshot. The Agent
controller owns continuation; neither a model argument nor an observation grants
an action, a new capture or a second Agent loop.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Protocol, runtime_checkable

ENABLED_FIELD = '_progressive_evidence_enabled'
PENDING_FIELD = '_progressive_evidence_pending'
CONTINUE_FIELD = '_progressive_evidence_continue'
MAX_AGE_SECONDS = 30.0
MAX_REPLY_CHARS = 2000
_SENTENCE_BOUNDARY = re.compile(r'[.!?…]["\'”’)\]*_]*(?=\s)|\n')
_SKIP = re.compile(r'[\W_]*skip[\W_]*', re.IGNORECASE)


@runtime_checkable
class EvidenceSequence(Protocol):
    tool: str
    arguments: dict

    @property
    def has_next(self) -> bool: ...

    def advance(self) -> dict: ...

    def close(self) -> None: ...


def _sentences(text: str) -> list[str]:
    ends = [match.start() if match.group() == '\n' else match.end()
            for match in _SENTENCE_BOUNDARY.finditer(text)] + [len(text)]
    start, parts = 0, []
    for end in ends:
        part = ' '.join(text[start:end].split())
        if part:
            parts.append(part)
        start = end
    return parts


def _identity(text: str) -> str:
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


class ProgressiveText:
    """One shared filter for early speech and the accepted final stage text.

    Only exact normalized sentences from completed earlier stages are omitted;
    this makes no claim to detect semantic paraphrases or contradictory facts.
    """
    def __init__(self) -> None:
        self.stages: list[str] = []
        self._seen: set[str] = set()
        self._prior: set[str] = set()
        self._streamed: list[str] = []

    def begin_stage(self) -> None:
        self._prior = set(self._seen)
        self._streamed = []

    def select(self, text: str) -> str:
        return ' '.join(part for part in _sentences(text)
                        if not _SKIP.fullmatch(part) and _identity(part) not in self._prior)

    def record_spoken(self, text: str) -> None:
        self._streamed.append(text.strip())

    def finish_stage(self, text: str) -> str:
        answer = self.select(text)
        spoken = ' '.join(self._streamed)
        if spoken and not answer.startswith(spoken):
            raise ValueError('Progressive final text differs from its early speech')
        if len(' '.join([*self.stages, answer])) > MAX_REPLY_CHARS:
            raise ValueError('Progressive reply exceeds the completion text bound')
        if answer:
            self.stages.append(answer)
            self._seen.update(_identity(part) for part in _sentences(answer))
        return answer

    @property
    def summary(self) -> str:
        return ' '.join(self.stages)


async def close_sequences(*sequences: EvidenceSequence | None) -> None:
    """Drain native cleanup once per distinct sequence, even through cancellation."""
    unique = {id(sequence): sequence for sequence in sequences if sequence is not None}
    if not unique:
        return

    def close() -> None:
        failure = None
        for sequence in unique.values():
            try:
                sequence.close()
            except Exception as error:
                failure = failure or error
        if failure is not None:
            raise failure

    work = asyncio.create_task(asyncio.to_thread(close))
    cancelled = False
    while not work.done():
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            cancelled = True
    try:
        work.result()
    finally:
        if cancelled:
            raise asyncio.CancelledError

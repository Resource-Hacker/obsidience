"""Token accounting through the selected runtime, without another tokenizer.

Text counts are cached by artifact and content hash. Whole requests are counted
after model acquisition using the server's own chat template, including media.
Unavailable runtimes use a conservative UTF-8 byte bound, never chars / 4.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

import httpx

from .runtime import ModelSpec

PROMPT_SAFETY_TOKENS = 256
_TEXT_COUNTS: OrderedDict[tuple, int] = OrderedDict()
_TEXT_COUNTS_LOCK = threading.Lock()
_TOKENIZER = httpx.Client(timeout=0.5, trust_env=False)


def _artifact_key(spec: ModelSpec) -> tuple:
    try:
        path = spec.model_path.resolve()
        stat = path.stat()
        return spec.base_url, spec.id, str(path), stat.st_size, stat.st_mtime_ns
    except (AttributeError, OSError):
        return spec.base_url, spec.id, spec.runtime


def _cached_count(key: tuple) -> int | None:
    with _TEXT_COUNTS_LOCK:
        count = _TEXT_COUNTS.get(key)
        if count is not None:
            _TEXT_COUNTS.move_to_end(key)
        return count


def _store_count(key: tuple, count: int) -> None:
    with _TEXT_COUNTS_LOCK:
        _TEXT_COUNTS[key] = count
        _TEXT_COUNTS.move_to_end(key)
        if len(_TEXT_COUNTS) > 128:
            _TEXT_COUNTS.popitem(last=False)


def _text_request(text: str, spec: ModelSpec) -> dict:
    body = {"content": text, "add_special": False, "parse_special": False}
    if not spec.runtime.startswith("llama.cpp"):
        body = {"model": spec.id, "prompt": text, "add_special_tokens": False}
    return body


def count_text(text: str, spec: ModelSpec) -> int:
    """Legacy synchronous count for callers outside the asynchronous turn path."""
    if not text:
        return 0
    encoded = text.encode("utf-8")
    key = (*_artifact_key(spec), hashlib.sha256(encoded).digest())
    cached = _cached_count(key)
    if cached is not None:
        return cached
    try:
        response = _TOKENIZER.post(spec.base_url.removesuffix("/v1") + "/tokenize",
                                   json=_text_request(text, spec))
        response.raise_for_status()
        tokens = response.json()["tokens"]
        if not isinstance(tokens, list):
            raise ValueError("invalid runtime tokens")
        count = len(tokens)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return len(encoded)
    _store_count(key, count)
    return count


@dataclass(frozen=True)
class PayloadCount:
    tokens: int
    method: str = "runtime"


def cached_text_count(text: str, spec: ModelSpec) -> PayloadCount:
    """Read meter state without contacting a runtime; identify an estimate."""
    if not text:
        return PayloadCount(0)
    encoded = text.encode("utf-8")
    key = (*_artifact_key(spec), hashlib.sha256(encoded).digest())
    cached = _cached_count(key)
    if cached is not None:
        return PayloadCount(cached)
    return PayloadCount(len(encoded), "utf8_upper_bound")


async def measure_text(text: str, spec: ModelSpec) -> PayloadCount:
    """Count occupancy asynchronously; only successful runtime counts are cached."""
    if not text:
        return PayloadCount(0)
    encoded = text.encode("utf-8")
    key = (*_artifact_key(spec), hashlib.sha256(encoded).digest())
    cached = _cached_count(key)
    if cached is not None:
        return PayloadCount(cached)
    from .llm import provider_client

    try:
        async with provider_client() as client:
            response = await client.post(
                spec.base_url.removesuffix("/v1") + "/tokenize",
                json=_text_request(text, spec), timeout=0.5,
            )
        response.raise_for_status()
        tokens = response.json()["tokens"]
        if not isinstance(tokens, list):
            raise ValueError("invalid runtime tokens")
        count = len(tokens)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return PayloadCount(len(encoded), "utf8_upper_bound")
    _store_count(key, count)
    return PayloadCount(count)


class ContextBudgetExceeded(ValueError):
    def __init__(self, count: PayloadCount, capacity: int):
        self.required_tokens = count.tokens
        self.available_tokens = capacity
        self.accounting = count.method
        measured = "input tokens" if count.method == "runtime" else "conservative UTF-8 token bound"
        super().__init__(
            f"Thinking Packet needs {count.tokens} {measured}; this model has "
            f"{capacity} available. The fixed packet and latest result cannot fit after "
            "recoverable earlier read pages are projected; the Objective has not been truncated."
        )


async def measure_payload(payload: dict, spec: ModelSpec, client: httpx.AsyncClient) -> PayloadCount:
    """Count exactly the same request that will be sent to chat/completions."""
    if spec.runtime.startswith("llama.cpp"):
        url = spec.base_url + "/chat/completions/input_tokens"
        body = payload
    else:
        url = spec.base_url.removesuffix("/v1") + "/tokenize"
        body = {"model": spec.id, "messages": payload["messages"],
                "add_generation_prompt": True,
                "chat_template_kwargs": payload.get("chat_template_kwargs", {})}
    try:
        response = await client.post(url, json=body, timeout=3)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("invalid runtime token envelope")
        count = data.get("input_tokens", data.get("count"))
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("invalid runtime token count")
        return PayloadCount(count)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        if any(isinstance(message.get("content"), list) for message in payload["messages"]):
            raise ValueError("model context accounting unavailable for a multimodal request")
        return PayloadCount(
            len(json.dumps(payload["messages"], ensure_ascii=False).encode("utf-8"))
            + PROMPT_SAFETY_TOKENS,
            "utf8_upper_bound",
        )


async def count_payload(payload: dict, spec: ModelSpec, client: httpx.AsyncClient) -> int:
    return (await measure_payload(payload, spec, client)).tokens


_PAGE_RANGE = re.compile(r"(?m)^Characters (\d+)-(\d+) of (\d+)\.[^\n]*\n\n")
_SOURCE_ID = re.compile(r"source://[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


@dataclass
class ReadPage:
    index: int
    header: str
    body: str
    citation: str
    offset: int
    total: int
    suffix: str
    original: str
    retained: int
    tool: str = "source.read"
    revision: str = ""

    def render(self, limit: int) -> str:
        keep = min(limit, self.retained, len(self.body))
        if keep == len(self.body):
            return self.original
        end = self.offset + keep
        if self.tool == "vault.read":
            recovery = json.dumps({"ref": self.citation, "offset": end,
                                   "expected_sha256": self.revision}, ensure_ascii=False, sort_keys=True)
            return (
                f"Observation:\n{self.header}"
                f"Context projection of an earlier Article page: characters {self.offset}-{end} "
                f"of {self.total}; the Tool originally returned through {self.offset + len(self.body)}.\n"
                f"Omitted text is not in this request. Recover it with vault.read using {recovery} "
                "only if needed; a changed Article or backlink snapshot fails explicitly. "
                "Do not infer omitted facts or silently substitute a newer view.\n\n"
                f"{self.body[:keep]}{self.suffix}"
            )
        return (
            f"Observation:\n{self.header}"
            f"Context projection of an earlier Source page: characters {self.offset}-{end} "
            f"of {self.total}; the Tool originally returned through {self.offset + len(self.body)}.\n"
            f"Omitted text is not in this request. Recover it with source.read using "
            f"source {self.citation} and offset {end} only if needed; do not infer omitted facts.\n\n"
            f"{self.body[:keep]}{self.suffix}"
        )


@dataclass
class ReadBatch:
    """Project each independently attested page without losing batch failures."""

    index: int
    envelope: dict
    pages: dict[int, ReadPage]
    suffix: str
    original: str
    retained: int

    def render(self, limit: int) -> str:
        keep = min(limit, self.retained)
        if all(keep >= len(page.body) for page in self.pages.values()):
            return self.original
        rows = [dict(row) for row in self.envelope["results"]]
        for number, page in self.pages.items():
            rows[number]["result"] = page.render(keep).removeprefix("Observation:\n")
        return "Observation:\n" + json.dumps(
            {**self.envelope, "results": rows}, ensure_ascii=False,
        ) + self.suffix


@dataclass
class TaskContext:
    """Request-only projection; fixed instructions, actions and effects stay exact.

    Only actual pageable read-only Tool envelopes are eligible. Their immutable
    Source or version-attested Article and offset are the recovery path. A prose citation
    inside an arbitrary Tool result cannot make that result discardable.
    """

    pages: dict[int, ReadPage | ReadBatch] = field(default_factory=dict)
    last_projection: dict = field(default_factory=dict)
    latest_result_index: int | None = None

    def remember_source_page(self, index: int, tool: str, observation: str,
                             suffix: str, *, source_read_allowed: bool) -> None:
        self.latest_result_index = index
        if not source_read_allowed or tool not in {"source.read", "web.fetch"}:
            return
        if self._remember_batch(index, tool, observation, suffix):
            return
        match = _PAGE_RANGE.search(observation)
        if match is None:
            return
        header, body = observation[:match.start()], observation[match.end():]
        citation = _SOURCE_ID.search(header)
        offset, end, total = map(int, match.groups())
        if citation is None or end < offset or end > total or len(body) != end - offset:
            return
        if tool == "source.read" and not header.startswith(citation.group() + " · "):
            return
        if tool == "web.fetch" and not header.startswith(("Fetched and captured ", "Fetched and verified ")):
            return
        original = f"Observation:\n{observation}{suffix}"
        page = ReadPage(index, header, body, citation.group(), offset, total,
                        suffix, original, len(body))
        if len(page.render(0)) < len(original):
            self.pages[index] = page

    def remember_article_page(self, index: int, tool: str, observation: str,
                              suffix: str, *, vault_read_allowed: bool) -> None:
        self.latest_result_index = index
        if not vault_read_allowed or tool != "vault.read":
            return
        if self._remember_batch(index, tool, observation, suffix):
            return
        if not observation.startswith("Article: "):
            return
        header, separator, remainder = observation.partition("\n")
        if not separator:
            return
        try:
            identity = json.loads(header.removeprefix("Article: "))
        except ValueError:
            return
        if not isinstance(identity, dict) or set(identity) != {"ref", "view_sha256"}:
            return
        ref, revision = identity["ref"], identity["view_sha256"]
        if (not isinstance(ref, str) or not ref or "\n" in ref
                or not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None):
            return
        match = _PAGE_RANGE.match(remainder)
        if match is None:
            return
        body = remainder[match.end():]
        offset, end, total = map(int, match.groups())
        if end < offset or end > total or len(body) != end - offset:
            return
        original = f"Observation:\n{observation}{suffix}"
        page = ReadPage(index, header + "\n", body, ref, offset, total, suffix,
                        original, len(body), tool="vault.read", revision=revision)
        if len(page.render(0)) < len(original):
            self.pages[index] = page

    def _remember_batch(self, index: int, tool: str, observation: str, suffix: str) -> bool:
        if not observation.startswith("{"):
            return False
        try:
            envelope = json.loads(observation)
        except ValueError:
            return False
        if not isinstance(envelope, dict) or set(envelope) != {"results"}:
            return False
        rows = envelope["results"]
        if (not isinstance(rows, list) or not 1 <= len(rows) <= 10
                or not all(isinstance(row, dict) for row in rows)):
            return False
        pages = {}
        for number, row in enumerate(rows):
            text = row.get("result")
            if row.get("ok") is not True or not isinstance(text, str) or text.startswith("{"):
                continue
            # Reuse the single-page parser. Arbitrary strings, malformed ranges,
            # nested batches and failed operations cannot become discardable.
            item = TaskContext()
            if tool == "vault.read":
                item.remember_article_page(0, tool, text, "", vault_read_allowed=True)
            else:
                item.remember_source_page(0, tool, text, "", source_read_allowed=True)
            if 0 in item.pages:
                pages[number] = item.pages[0]
        if pages:
            original = f"Observation:\n{observation}{suffix}"
            batch = ReadBatch(index, envelope, pages, suffix, original,
                              max(page.retained for page in pages.values()))
            if len(batch.render(0)) < len(original):
                self.pages[index] = batch
        return True

    async def fit_payload(self, payload: dict, spec: ModelSpec,
                          client: httpx.AsyncClient, capacity: int) -> PayloadCount:
        # The most recent result has not yet informed an action and remains
        # complete, including any unconsumed private image.
        messages = [dict(message) for message in payload["messages"]]
        payload["messages"] = messages
        pages = [
            page for index, page in self.pages.items()
            if index < len(messages) - 1
            and index != self.latest_result_index
            and messages[index].get("role") == "user"
            and messages[index].get("content") == page.original
        ]
        for page in pages:
            messages[page.index]["content"] = page.render(page.retained)
        before = await measure_payload(payload, spec, client)
        self.last_projection = {
            "input_tokens": before.tokens, "input_capacity_tokens": capacity,
            "accounting": before.method,
            **self._projection_counts(pages),
        }
        if before.tokens <= capacity:
            return before
        if not pages:
            raise ContextBudgetExceeded(before, capacity)

        def project(limit: int) -> None:
            for page in pages:
                messages[page.index]["content"] = page.render(limit)

        project(0)
        minimum = await measure_payload(payload, spec, client)
        if minimum.tokens > capacity:
            raise ContextBudgetExceeded(minimum, capacity)
        # A finite binary search retains the largest tested common page prefix.
        # Every accepted candidate is counted using the complete provider wire
        # payload. No inference, Tool retry or model-setting change is involved.
        low, high = 0, max(page.retained for page in pages)
        best = minimum
        while low + 1 < high:
            middle = (low + high) // 2
            project(middle)
            count = await measure_payload(payload, spec, client)
            if count.tokens <= capacity:
                low, best = middle, count
            else:
                high = middle
        project(low)
        for page in pages:
            page.retained = min(page.retained, low)
        self.last_projection = {
            "input_tokens": best.tokens, "input_capacity_tokens": capacity,
            "accounting": best.method, "before_input_tokens": before.tokens,
            **self._projection_counts(pages),
        }
        return best

    @staticmethod
    def _projection_counts(pages: list[ReadPage | ReadBatch]) -> dict[str, int]:
        entries = [
            (item, min(page.retained, item.retained))
            for page in pages
            for item in (page.pages.values() if isinstance(page, ReadBatch) else (page,))
        ]
        return {
            "source_pages_projected": sum(page.tool == "source.read" and kept < len(page.body) for page, kept in entries),
            "article_pages_projected": sum(page.tool == "vault.read" and kept < len(page.body) for page, kept in entries),
        }


def discard_consumed_images(messages: list[dict]) -> None:
    """A successful inference consumes an image's one-request private lifetime."""
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            message["content"] = "\n".join(
                str(part["text"]) for part in content
                if isinstance(part, dict) and part.get("type") == "text" and "text" in part
            )

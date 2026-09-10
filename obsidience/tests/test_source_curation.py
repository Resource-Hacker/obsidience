from __future__ import annotations

from copy import deepcopy

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import curation, index, review, source
from obsidience.harness.knowledge.source import SourceError
from obsidience.harness.knowledge.vault import write_note
from obsidience.harness.web import feeds


def _citation(number: int) -> str:
    return f"source://00000000-0000-0000-0000-{number:012d}"


def _article(number: int, url: str | None = None, **overrides) -> dict:
    citation = _citation(number)
    values = {
        "id": citation.removeprefix("source://"),
        "citation": citation,
        "source_type": "tool",
        "source_ref": url or f"https://news.example/articles/story-{number}",
        "media_type": "text/markdown",
        "captured_at": "2026-09-04T20:00:00.000Z",
        "content_sha256": f"sha256:story-{number}",
        "immutable": True,
        "status": "verified",
        "content": f"Fetched article {number}.",
    }
    values.update(overrides)
    return values


def _finding(citations: list[str]) -> str:
    return "A source-backed research finding.\n\nEvidence: " + " ".join(citations)


@pytest.fixture
def source_documents(monkeypatch) -> dict[str, dict]:
    documents = {_citation(number): _article(number) for number in range(1, 4)}

    def get_source(citation: str) -> dict:
        try:
            return deepcopy(documents[citation])
        except KeyError as exc:
            raise SourceError(f"source not found: {citation}") from exc

    monkeypatch.setattr(source, "get_source", get_source)
    monkeypatch.setattr(curation, "get_source", get_source)
    monkeypatch.setattr(
        feeds,
        "_public_url",
        lambda *_args, **_kwargs: pytest.fail("approval canonicalization performed DNS"),
    )
    return documents


class _SourceIndex:
    def __init__(self, row: dict) -> None:
        self.row = row

    def source(self, source_id: str) -> dict | None:
        return self.row if source_id == self.row["id"] else None


@pytest.fixture
def auto_curate(monkeypatch, tmp_path, source_documents):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    write_note(
        "News & Research/News & Research.md",
        {
            "title": "News & Research",
            "kind": "knowledge",
            "tags": ["auto-curate"],
            "curation_task": "[[Tasks/ingest]]",
            "research_task": "[[Tasks/research/question]]",
        },
        "Owner-selected publication policy.",
    )
    write_note(
        "Tasks/ingest.md",
        {
            "title": "Ingest",
            "kind": "task",
            "status": "running",
            "last_run": "ingest-run",
        },
        "Ingest one source.",
    )

    handoff_citation = _citation(99)
    handoff = {
        "id": handoff_citation.removeprefix("source://"),
        "citation": handoff_citation,
        "source_type": "research",
        "source_ref": "Research findings",
        "media_type": "text/markdown",
        "captured_at": "2026-09-04T20:05:00.000Z",
        "content_sha256": "sha256:handoff",
        "immutable": True,
        "status": "verified",
        "content": _finding(list(source_documents)),
    }
    source_documents[handoff_citation] = handoff
    row = {
        "id": handoff["id"],
        "path": "inbox/2026-09-04/research--handoff.md",
        "event_key": (
            "source.inbox:research:research-run:Tasks/research/question:content-id"
        ),
    }
    monkeypatch.setattr(index.INDEX, "source", _SourceIndex(row).source)
    monkeypatch.setattr(
        source,
        "_research_owner",
        lambda task, run_id: task == "Tasks/research/question" and run_id == "research-run",
    )
    approvals = []
    monkeypatch.setattr(
        review,
        "approve",
        lambda name: approvals.append(name) or {"approved": "News & Research/Research findings.md"},
    )

    result = {
        "staged": str(tmp_path / "_staging" / "proposal.md"),
        "target": "News & Research/Research findings.md",
        "action": "create",
        "review_class": "article",
    }
    body = handoff["content"] + f"\n\nInbox: {handoff_citation}\n\n[[News & Research/News & Research]]"
    args = {
        "target": result["target"],
        "action": result["action"],
        "title": "Research findings",
        "body": body,
        "metadata": {"kind": "knowledge"},
    }
    params = {
        "activation_key": row["event_key"],
        "source_id": handoff["id"],
        "source_citation": handoff["citation"],
        "source_path": f"obsidience/evidence/{row['path']}",
        "source_type": handoff["source_type"],
        "source_ref": handoff["source_ref"],
        "source_media_type": handoff["media_type"],
        "source_captured_at": handoff["captured_at"],
        "source_sha256": handoff["content_sha256"],
        "source_citations": list(source_documents)[:-1],
        "research_task": "Tasks/research/question",
        "research_run_id": "research-run",
    }
    context = {
        "task": "Tasks/ingest",
        "agent": "Alexandria",
        "event": "source.inbox",
        "run_id": "ingest-run",
        "params": params,
    }
    return {
        "result": result,
        "args": args,
        "context": context,
        "handoff": handoff,
        "approvals": approvals,
        "vault": tmp_path,
    }


@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("metadata", [{"kind": "knowledge"}, {"type": "knowledge"}])
def test_source_bound_research_publication_keeps_ordinary_policy(auto_curate, action, metadata):
    auto_curate["result"]["action"] = action
    auto_curate["args"]["action"] = action
    auto_curate["args"]["metadata"] = metadata
    if action == "update":
        write_note(auto_curate["result"]["target"], {"title": "Research findings", "kind": "knowledge"},
                   "An earlier accepted finding.")
    outcome = curation.try_auto_approve(auto_curate["result"], auto_curate["args"], auto_curate["context"])
    assert outcome["auto_approved"] is True
    assert auto_curate["approvals"] == ["proposal.md"]


@pytest.mark.parametrize(
    "fault",
    [
        "toggle_off",
        "wrong_task",
        "wrong_ingest_run",
        "wrong_research_run",
        "wrong_citation",
        "wrong_hash",
        "policy_edit",
        "wrong_kind",
        "authority_metadata",
        "archive",
        "outside_branch",
        "unresolved_link",
    ],
)
def test_auto_curate_faults_leave_the_proposal_for_review(auto_curate, fault):
    result = auto_curate["result"]
    args = auto_curate["args"]
    context = auto_curate["context"]
    if fault == "toggle_off":
        write_note(
            "News & Research/News & Research.md",
            {
                "title": "News & Research",
                "kind": "knowledge",
                "tags": [],
                "curation_task": "[[Tasks/ingest]]",
                "research_task": "[[Tasks/research/question]]",
            },
            "Auto-curate disabled.",
        )
    elif fault == "wrong_task":
        context["task"] = "Tasks/query"
    elif fault == "wrong_ingest_run":
        context["run_id"] = "other-ingest-run"
    elif fault == "wrong_research_run":
        context["params"]["research_run_id"] = "other-research-run"
    elif fault == "wrong_citation":
        context["params"]["source_citation"] = _citation(404)
    elif fault == "wrong_hash":
        context["params"]["source_sha256"] = "sha256:wrong"
    elif fault == "policy_edit":
        result["target"] = "News & Research/News & Research.md"
        args["target"] = result["target"]
    elif fault == "wrong_kind":
        args["metadata"] = {"kind": "agent"}
    elif fault == "authority_metadata":
        args["metadata"] = {"kind": "knowledge", "tags": ["auto-curate"]}
    elif fault == "archive":
        result["action"] = "archive"
        args["action"] = "archive"
    elif fault == "outside_branch":
        result["target"] = "Projects/Research findings.md"
        args["target"] = result["target"]
    elif fault == "unresolved_link":
        args["body"] += "\n\n[[Missing/Article]]"

    outcome = curation.try_auto_approve(result, args, context)

    assert "auto_approved" not in outcome
    assert auto_curate["approvals"] == []
    assert outcome["staged"].endswith("proposal.md")

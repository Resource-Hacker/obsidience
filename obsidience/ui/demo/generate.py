#!/usr/bin/env python3
"""Build the interactive graph demo's static data: Obsidience describing itself.

Every input is public and comes from this repository:

- Knowledge: the tracked starter Vault (``obsidience/defaults/vault``) through
  the real Harness Knowledge projection: the Executive's graph and its
  specialist satellites.
- Code: this repository's codebase-memory-mcp layout (one read-only GET to the
  local provider) through the real Code adapter, limited to tracked files.
- Memory: a Hindsight-shaped bank generated from the repository history:
  commit subjects and dates (experiences), sentences quoted from DESIGN.md and
  docs/ (world facts) and observations counted from that history, linked by
  time, shared files and topic, through the real Memory projection.
- Showcase: the tour's Knowledge activity and Action Trace frames, recorded
  from the real emitters with a Thinking Packet compiled from the starter Vault.

The projections run in a temporary copy of the Harness whose Vault is the
starter Vault, inside a private network namespace (``unshare -rn``), so nothing
can reach a running Harness, Hindsight, embedding service or model.

Usage (from the repository root, with the Harness virtualenv):
    .venv/bin/python obsidience/ui/demo/generate.py [--layout saved-layout.json]
    .venv/bin/python obsidience/ui/demo/leak_check.py
Writes obsidience/ui/demo/public/data/*.json.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

DEMO = Path(__file__).resolve().parent
REPO = DEMO.parents[2]
OUT = DEMO / "public" / "data"
PROVIDER = "http://127.0.0.1:9749"
PROJECT = "obsidience"  # The published project name; the provider's is the checkout path.

# ---------------------------------------------------------------------------
# Repository history -> memory inputs (parent process)

# Commits about the owner's own devices, accounts, media, games or bots are
# left out; the rest describe the software itself.
PRIVATE = re.compile(
    r"discord|bard|squanch|omnibot|youtube|pluto|stremio|torbox|prowlarr|media|music|series|season|"
    r"\btv\b|fire ?os|moonlight|sunshine|snapcast|android|edge\b|browser|camera|webcam|obsbot|brio|"
    r"kinect|vr\b|wivrn|steam|wow\b|warcraft|game|tft|teamfight|lights?\b|wiz\b|visualizer|"
    r"rtx|4080|4000|ada\b|igpu|gpu|nvidia|cuda|uma-?8|minidsp|samsung|monitor|display|hdmi|dp-\d|usb|"
    r"pci|bios|owner'?s? name|names|member|account|credential|password|token|secret|login|"
    r"@|https?://|/home|wissenschafter|private|personal|consent|dataset|sample|"
    r"workstation|admech|harness@|revert|television|mouse|dpi\b|keyd", re.IGNORECASE)

_HASHES: set[str] | None = None


def is_private(text: str) -> bool:
    """An owner-specific topic, or a term on the local hashed private-term list (see leak_check)."""
    global _HASHES
    sys.path.insert(0, str(DEMO))
    from leak_check import private_hashes, scan
    if _HASHES is None:
        _HASHES = private_hashes()
    return bool(PRIVATE.search(text)) or any(f.startswith("private term") for f in scan(text, _HASHES))


TOPICS = [  # (topic, subject keywords, path prefixes), first match wins
    ("Voice", r"voice|speech|speak|asr|stt|tts|wake|smart turn|end.of.turn|turn.taking|turn verdict|vad|silero|pocket|barge|transcript|utterance|"
              r"playback|chirp|audio|microphone|pipecat|nemo|realtime|smart turn|admission",
     ("obsidience/harness/realtime/", "obsidience/harness/execution/speech", "docs/modules/harness/voice",
      "docs/integrations/voice-stack")),
    ("Memory", r"hindsight|memor|recall|retain|consolidat|mental model|observation",
     ("obsidience/harness/memory/", "obsidience/harness/graphs/memory", "docs/memory", "docs/integrations/hindsight")),
    ("Self-improvement", r"harness2|audit|optimi[sz]|autosaddler|trial|holdout|baseline|candidate|incident",
     ("obsidience/harness/improvement", "docs/harness2", "docs/integrations/harness2",
      "docs/modules/harness/self-improvement")),
    ("Graph UI", r"graph|render|shader|glass|marble|beam|label|crater|orb|action trace|thinking|comet|ripple|"
                 r"satellite|three\.js|webgl|canvas|stage|pane",
     ("obsidience/ui/", "docs/modules/shell/graph-ui")),
    ("Code graph", r"code graph|codebase|code lookup|code stage|symbol",
     ("obsidience/harness/graphs/codebase", "obsidience/harness/graphs/agent_activity", "docs/integrations/code-graph")),
    ("Knowledge", r"vault|article|okf|ontology|knowledge|review|library|curat|link|projection|runbook|skill|"
                  r"wiki|proposal|alexandria|darwin|heimdall",
     ("obsidience/harness/knowledge/", "obsidience/defaults/vault/", "docs/ontology", "docs/articles",
      "docs/integrations/okf")),
    ("Executive", r"executive|adk|tool|task|scheduler|model|llama|gemma|prompt|packet|activation|conversation|"
                  r"reply|answer|completion|capabilit|receipt|run\b|slot|cache",
     ("obsidience/harness/execution/", "obsidience/harness/conversation/", "obsidience/harness/capabilities/",
      "docs/integrations/google-adk", "docs/integrations/llama-cpp")),
    ("Shell", r"shell|hyprland|quickshell|qml|surface|desktop|lock|terminal|window|workspace|session",
     ("obsidience/shell/", "docs/modules/shell")),
    ("Docs", r"docs?\b|document|readme|mkdocs|guide|site", ("docs/", "README", "DESIGN.md")),
]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout


def utc(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone(timezone.utc).isoformat()


def topic_of(subject: str, files: list[str]) -> str:
    for topic, words, prefixes in TOPICS:
        if re.search(words, subject, re.IGNORECASE):
            return topic
    for topic, _words, prefixes in TOPICS:
        if any(path.startswith(prefixes) for path in files):
            return topic
    return ""


def collect_history(ref: str) -> list[dict]:
    """Public commits on `ref` by the project's GitHub identity, oldest first."""
    raw = git("log", ref, "--no-merges", "--format=%x1e%H%x1f%aI%x1f%ae%x1f%s", "--name-only")
    commits = []
    for block in raw.split("\x1e")[1:]:
        head, _, names = block.partition("\n")
        sha, when, email, subject = head.split("\x1f")
        when = utc(when)
        if not email.endswith("@users.noreply.github.com") or is_private(subject):
            continue
        files = [line for line in names.splitlines() if line.strip()]
        topic = topic_of(subject, files)
        if not topic:
            continue
        commits.append({"sha": sha[:9], "when": when, "subject": subject.strip(), "files": files, "topic": topic})
    commits.sort(key=lambda c: c["when"])
    return commits


def _plain(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?<!\w)([*_]{1,2})([^*_\n]+?)\1(?!\w)", r"\2", text)  # emphasis, not snake_case
    return " ".join(text.replace("`", "").split())


def collect_facts(ref: str) -> list[dict]:
    """First sentences of prose paragraphs in DESIGN.md and docs/ on `ref`, dated by their last commit."""
    files = [name for name in git("ls-tree", "-r", "--name-only", ref, "--", "DESIGN.md", "docs").splitlines()
             if name.endswith(".md") and "/hooks/" not in name and not name.endswith("README-section.md")]
    facts = []
    for name in files:
        when = git("log", "-1", "--format=%aI", ref, "--", name).strip()
        if not when:
            continue
        when = utc(when)
        text = git("show", f"{ref}:{name}")
        text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        picked = 0
        for paragraph in re.split(r"\n\s*\n", text):
            lines = paragraph.strip().splitlines()
            if not lines or lines[0].lstrip().startswith(("#", "|", "-", "*", ">", "<", "!", "1.", ":", "[", "=")):
                continue
            sentence = re.split(r"(?<=[.!?])\s+(?=[A-Z])", _plain(" ".join(lines)))[0]
            if not 50 <= len(sentence) <= 230 or not sentence.endswith(".") or is_private(sentence) \
                    or re.search(r"\d+\.\d+\.\d+\.\d+|:\d{4}\b", sentence):
                continue
            topic = topic_of(sentence, [name]) or "Docs"
            facts.append({"source": name, "when": when, "text": sentence, "topic": topic})
            picked += 1
            if picked >= 6:
                break
    return facts


def provider_project() -> str:
    """The provider names a project by its main checkout's path (a worktree shares that index)."""
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    return str(common.parent).strip("/").replace("/", "-")


def fetch_layout() -> dict:
    query = urllib.parse.urlencode({"project": provider_project(), "max_nodes": 14000})
    with urllib.request.urlopen(f"{PROVIDER}/api/layout?{query}", timeout=60) as response:
        return json.load(response)


def public_layout(layout: dict) -> dict:
    """Only nodes of tracked files (and their file-less symbols), under the published project name."""
    tracked = set(git("ls-files").splitlines())
    folders = {str(Path(path).parents[i]) for path in tracked for i in range(len(Path(path).parents) - 1)}
    keep = {}
    for node in layout["nodes"]:
        path = node.get("file_path") or ""
        if node.get("label") == "Project":
            keep[node["id"]] = {**node, "name": PROJECT, "qualified_name": PROJECT}
        elif path in tracked or (node.get("label") == "Folder" and path in folders):
            keep[node["id"]] = node
        elif not path:
            keep[node["id"]] = node  # routes, variables and decorators found in code; pruned below
    edges = [e for e in layout["edges"] if e["source"] in keep and e["target"] in keep]
    linked = {e["source"] for e in edges} | {e["target"] for e in edges}
    prefix = provider_project() + "."
    sys.path.insert(0, str(DEMO))
    from leak_check import private_hashes, scan
    hashes = private_hashes()
    nodes = []
    for node in keep.values():
        if not node.get("file_path") and node.get("label") != "Project" and node["id"] not in linked:
            continue
        qualified = node.get("qualified_name") or ""
        if qualified.startswith(prefix):
            qualified = PROJECT + "." + qualified[len(prefix):]
        if scan(" ".join((str(node.get("name") or ""), qualified, str(node.get("file_path") or ""))), hashes):
            continue  # a private name or runtime path in a symbol, heading or route
        nodes.append({**node, "qualified_name": qualified})
    ids = {node["id"] for node in nodes}
    return {"nodes": nodes, "edges": [e for e in edges if e["source"] in ids and e["target"] in ids],
            "total_nodes": len(nodes)}


# ---------------------------------------------------------------------------
# Projections (child process, inside unshare -rn, in a temporary Harness copy)

QUESTION = "How does speech turn-taking decide I've finished speaking?"
RECALL_QUESTION = "What changed in the voice pipeline recently?"
# The lookup and its returned symbols, as the code-graph MCP answered it on 2026-10-20.
CODE_QUERY = "smart turn end of turn verdict"
CODE_RESULTS = [
    "obsidience.harness.realtime.speech.worker.smart_turn_analyzer",
    "obsidience.harness.realtime.speech.worker.ObsidienceNeMoTurnTakingService.turn_pending",
    "obsidience.harness.realtime.speech.worker._turn_words",
    "obsidience.harness.execution.native_turn.turn_recall",
    "obsidience.harness.conversation.runtime.ConversationRuntime._run_turn",
    "obsidience.harness.conversation.runtime.ConversationRuntime.active_turn",
    "obsidience.harness.execution.trace.bind_turn",
]
EPOCH = datetime.fromisoformat("2026-10-20T18:00:00+00:00")


class _Response:
    def __init__(self, doc):
        self.doc = doc

    def raise_for_status(self):
        pass

    def json(self):
        return self.doc


class _Clock:
    """The recorder's virtual clock: milliseconds since the tour began."""

    def __init__(self):
        self.ms = 0.0

    def time(self):
        return self.ms / 1000

    def monotonic_ns(self):
        return int(self.ms * 1_000_000) + 10**12

    def perf_counter(self):
        return self.ms / 1000

    def monotonic(self):
        return self.ms / 1000


def build_memory(bank: str, history: list[dict], facts: list[dict]):
    """Hindsight's native /graph document and records for the history bank."""
    import uuid

    def ident(key: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"obsidience-demo/{key}"))

    rows = []
    for commit in history:
        rows.append({"id": ident(commit["sha"]), "text": commit["subject"].rstrip(".") + f" (commit {commit['sha'][:7]}).",
                     "kind": "experience", "topic": commit["topic"], "when": commit["when"], "files": commit["files"]})
    for fact in facts:
        rows.append({"id": ident(fact["source"] + fact["text"]), "text": fact["text"], "kind": "world",
                     "topic": fact["topic"], "when": fact["when"], "files": [fact["source"]]})
    # Observations: counted from the commits of one topic in one month.
    by_month = defaultdict(list)
    for commit in history:
        by_month[(commit["topic"], commit["when"][:7])].append(commit)
    for (topic, month), commits in sorted(by_month.items()):
        if len(commits) < 4:
            continue
        files = Counter(path for commit in commits for path in commit["files"]
                        if not path.startswith(("docs/", "README", "artifacts.lock")))
        top = ", ".join(Path(path).name for path, _ in files.most_common(2))
        label = datetime.fromisoformat(commits[0]["when"]).strftime("%B %Y")
        text = (f"In {label}, {len(commits)} commits changed the {topic.lower()} area"
                + (f", most often {top}." if top else "."))
        rows.append({"id": ident(f"obs/{topic}/{month}"), "text": text, "kind": "observation", "topic": topic,
                     "when": max(c["when"] for c in commits), "files": [],
                     "support": [ident(c["sha"]) for c in commits[-12:]]})
    rows.sort(key=lambda r: r["when"])
    edges = []
    for index, row in enumerate(rows):  # Hindsight links each memory to its neighbours in time.
        for step in (1, 2):
            if index + step < len(rows):
                edges.append((row["id"], rows[index + step]["id"], "temporal", 1.0))
    last_by_file, by_topic = {}, defaultdict(list)
    for row in rows:  # entity: the previous memory about the same file; semantic: same topic, near in time
        for path in row["files"][:12]:
            if path in last_by_file:
                edges.append((last_by_file[path], row["id"], "entity", 1.0))
            last_by_file[path] = row["id"]
        for other in by_topic[row["topic"]][-3:]:
            edges.append((other, row["id"], "semantic", 0.72))
        by_topic[row["topic"]].append(row["id"])
    seen, unique = set(), []
    for edge in edges:
        if edge[0] != edge[1] and edge[:3] not in seen:
            seen.add(edge[:3])
            unique.append(edge)
    newest = sorted(rows, key=lambda r: r["when"], reverse=True)
    doc = {"nodes": [{"data": {"id": r["id"], "label": r["text"][:40], "text": r["text"], "entities": r["topic"]}}
                     for r in newest],
           "edges": [{"data": {"id": f"e{i}", "source": s, "target": t, "linkType": kind, "weight": weight,
                               "color": "#6d8baa"}} for i, (s, t, kind, weight) in enumerate(unique)],
           "table_rows": [{"id": r["id"], "text": r["text"], "fact_type": r["kind"], "mentioned_at": r["when"],
                           "occurred_start": r["when"] if r["kind"] == "experience" else None, "occurred_end": None,
                           "tags": [r["topic"]], "proof_count": len(r.get("support", []))} for r in newest],
           "total_units": len(rows)}
    records = {r["id"]: {"id": r["id"], "text": r["text"], "fact_type": r["kind"], "mentioned_at": r["when"],
                         "source_memory_ids": r.get("support", [])} for r in rows}
    return doc, records, rows


def article_previews(iter_notes) -> dict:
    previews = {}
    for note in iter_notes():
        body = re.sub(r"```.*?```", "", note.body, flags=re.DOTALL)
        paragraphs = [_plain(p) for p in re.split(r"\n\s*\n", body)
                      if p.strip() and not p.lstrip().startswith(("#", "|", "-", "*", ">", "<"))]
        excerpt = " ".join(paragraphs)[:420]
        previews[note.ref] = {"title": note.title, "type": note.kind, "path": note.path,
                              "excerpt": excerpt + ("…" if len(" ".join(paragraphs)) > 420 else "")}
    return previews


def child(work: Path) -> None:
    import asyncio
    import types
    root = work / "root"
    sys.path.insert(0, str(root))
    from obsidience.harness.config import CONFIG
    assert CONFIG.project_root == root and CONFIG.vault_dir == root / "obsidience" / "vault", CONFIG.project_root
    from obsidience.harness.knowledge.index import INDEX
    from obsidience.harness.knowledge import projection
    from obsidience.harness.knowledge.vault import iter_notes, load_note, resolver
    from obsidience.harness.memory import hindsight
    from obsidience.harness.graphs import codebase, memory as memory_projection
    from obsidience.harness.interfaces.api.routes import graphs as graph_routes
    from obsidience.harness.execution import activity, trace
    from obsidience.harness.graphs.agent_activity import lookup_detail
    from obsidience.harness.execution.native_turn import trace_recall

    out = Path(sys.argv[sys.argv.index("--out") + 1])
    history = json.loads((work / "history.json").read_text())
    facts = json.loads((work / "facts.json").read_text())

    INDEX.sync(embed=False)
    graph = projection.graph()
    graph.pop("link_proposals", None)
    (out / "graph.json").write_text(json.dumps(graph, separators=(",", ":")))
    (out / "articles.json").write_text(json.dumps(article_previews(iter_notes), separators=(",", ":")))
    print("knowledge", len(graph["nodes"]), "nodes", len(graph["links"]), "links",
          [g["id"] for g in graph["navigation"]["groups"]], flush=True)

    layout = json.loads((work / "layout.json").read_text())
    CONFIG.extras["graphs"] = {"codebase_project": PROJECT}
    codebase._client = types.SimpleNamespace(get=lambda url, params=None, headers=None: _Response(layout))
    code = codebase.project(14000)
    for node in code["nodes"]:  # display coordinates need no float64 precision
        for axis in ("x", "y", "z"):
            node[axis] = round(node[axis], 1)
    (out / "code.json").write_text(json.dumps(code, separators=(",", ":")))
    print("code", len(code["nodes"]), "nodes", len(code["edges"]), "edges", flush=True)

    agent = "Agents/Executive/Executive"
    bank = hindsight.bank_for(agent)
    doc, records, rows = build_memory(bank, history, facts)
    MEMORY = hindsight.MEMORY
    MEMORY.banks = {bank: agent}
    MEMORY.records = {bank: records}
    MEMORY.updated_at = history[-1]["when"]
    MEMORY.status = lambda: {"status": "healthy", "provider": "hindsight"}

    def graph_read(_bank, path, **params):
        if path == "/stats":
            return {"total_nodes": len(doc["nodes"]), "total_links": len(doc["edges"])}
        if path == "/graph":
            return doc
        raise AssertionError(path)
    MEMORY.graph_read = graph_read
    banks = graph_routes.banks()
    memory = memory_projection.project(bank)
    (out / "banks.json").write_text(json.dumps(banks, separators=(",", ":")))
    (out / "memory.json").write_text(json.dumps(memory, separators=(",", ":")))
    print("memory", len(memory["nodes"]), "records", len(memory["edges"]), "edges", Counter(
        n["kind"] for n in memory["nodes"]), flush=True)

    # ---- the tour, recorded from the real emitters on a virtual clock ----
    clock = _Clock()
    activity.time = trace.time = types.SimpleNamespace(time=clock.time, monotonic_ns=clock.monotonic_ns,
                                                       perf_counter=clock.perf_counter, monotonic=clock.monotonic)
    frames, entries = [], []
    publish_activity, publish_trace = activity._publish, trace._publish

    def record_activity(event, *, retain=True):
        frames.append({"t": round(clock.ms), "frame": {"type": "activity", **json.loads(json.dumps(event))}})
        return publish_activity(event, retain=retain)

    def record_trace(entry):
        entry["seq"] = len(entries) + 1
        entries.append({"t": round(clock.ms), "entry": json.loads(json.dumps(entry))})
        publish_trace(entry)
    activity._publish, trace._publish = record_activity, record_trace

    def at(seconds):
        clock.ms = seconds * 1000

    by_id = {r["id"]: r for r in rows}

    def recalled(topic_words, count):
        hits = [r for r in rows if r["kind"] != "observation" and r["topic"] == "Voice"
                and re.search(topic_words, r["text"], re.IGNORECASE)]
        return hits[-count:][::-1]

    def memory_value(hits, duration):
        return {"status": "returned", "duration_ms": duration, "memories": [
            {"ref": hindsight.memory_ref(bank, r["id"]), "type": r["kind"], "text": r["text"],
             "mentioned_at": r["when"], "occurred_start": r["when"] if r["kind"] == "experience" else None}
            for r in hits]}

    import uuid
    rng_ids = iter(uuid.uuid5(uuid.NAMESPACE_URL, f"obsidience-demo/run/{i}").hex for i in range(100))
    run_id, turn_id = next(rng_ids), next(rng_ids)
    executive = load_note(agent + ".md")
    tour = {"segments": [], "question": QUESTION, "recall_question": RECALL_QUESTION, "code_query": CODE_QUERY}

    # Segment: a spoken question on the Knowledge graph (begins 0 s into its segment).
    at(0.0)
    trace.latency("speech_final", duration_ms=412.0, turn_id=turn_id)
    activity.emit("admission_started", [agent], turn_id=turn_id)
    at(0.12)
    trace.latency("input_final", turn_id=turn_id)
    trace.emit("event", "Voice request received", [agent, "realtime"])
    at(0.2)
    # A conversation run is its Agent's turn: the executor binds the Agent as
    # both the run's Task and Agent (the Action Trace then labels it a Turn).
    token = trace.bind(run_id, agent, agent)
    trace.emit("run", "Computer turn started", ["model: obsidience-gemma; reasoning: none"],
               {"payload": {
                   "kind": "run", "status": "running", "task_title": "Computer", "agent_title": "Computer",
                   "model": "obsidience-gemma", "reasoning_effort": "none",
                   "summary": "model: obsidience-gemma; reasoning: none"}})
    activity.emit("query_started", [agent], query=QUESTION, run_id=run_id, turn_id=turn_id)
    at(0.8)

    # Two installation readings become demo constants: the workstation clock and
    # timezone, and the dense retrieval lane (no embedding service is reachable
    # here, so retrieval keeps the lexical lane the non-interactive Task path uses).
    from obsidience.harness.conversation import context_bindings
    from obsidience.harness.knowledge import retrieval
    context_bindings.local_clock = lambda: {"iso": EPOCH.isoformat(timespec="seconds"), "timezone": "UTC",
                                            "time": EPOCH.strftime("%I:%M %p UTC").lstrip("0"),
                                            "weekday": EPOCH.strftime("%A")}
    lexical_context = retrieval.fast_context_with_refs
    retrieval.fast_context_with_refs = lambda *a, **k: lexical_context(*a, **{**k, "relevant_only": False})

    async def compile_packet():
        from obsidience.harness.execution.executor import compile_activation
        return await compile_activation(executive, params={"request": QUESTION}, interactive=True,
                                        emit_activity=True, run_id=run_id, accepted_resolver=resolver(include_system=False))
    compiled = asyncio.run(compile_packet())
    packet_refs = compiled["refs"]
    trace.latency("activation", duration_ms=118.4, turn_id=turn_id, run_id=run_id)
    at(1.05)
    hits = recalled(r"smart turn|end.of.turn|turn verdict|pause|silence|vad|endpoint|semantic ?turn|speculat|early final", 5)
    trace_recall(lambda channel, line, detail, fields: trace.emit(channel, line, detail, fields),
                 memory_value(hits, 96.0), (QUESTION, ""), supplied=True, duration_ms=12.5)
    activity.emit_operation("search", "returned", [hindsight.memory_ref(bank, r["id"]) for r in hits],
                            label="Memories recalled", graph_id="memory:" + bank, run_id=run_id)
    at(1.3)
    trace.emit("model", "Computer model started", [], {"run_id": run_id, "step": 1, "payload": {
        "kind": "model", "phase": "started", "model": "obsidience-gemma", "model_label": "Gemma (local)"}})
    at(1.9)
    search_args = {"query": "speech turn end"}
    trace.emit("tool", "Computer → vault.search", [json.dumps(search_args)], {"run_id": run_id, "step": 2,
               "call_id": f"{run_id}:2", "payload": {"kind": "tool", "name": "vault.search", "phase": "start",
                                                     "arguments": search_args}})
    from obsidience.harness.knowledge.retrieval import fast_context_with_refs
    _brief, search_refs = fast_context_with_refs(search_args["query"], set(), 600, 4,
                                                 accepted_resolver=resolver(include_system=False))
    at(2.05)
    result = {"results": [{"ref": ref, "title": (load_note(ref + ".md") or executive).title} for ref in search_refs]}
    trace.emit("result", "vault.search returned", [json.dumps(result)], {"run_id": run_id, "step": 2,
               "call_id": f"{run_id}:2", "payload": {"kind": "tool", "name": "vault.search", "phase": "result",
                                                     "status": "returned", "duration_ms": 148.2, "result": result}})
    activity.emit_operation("search", "returned", search_refs, label="vault.search", graph_id="main", run_id=run_id)
    at(2.6)
    trace.latency("model_first_public", duration_ms=640.0, turn_id=turn_id, run_id=run_id)
    trace.emit("model", "Computer model returned", [], {"run_id": run_id, "step": 3, "payload": {
        "kind": "model", "phase": "result", "model": "obsidience-gemma", "model_label": "Gemma (local)",
        "metrics": {"prompt_tokens": 6120, "cached_input_tokens": 5890, "output_tokens": 74,
                    "first_public_delta_ms": 212.0, "generation_ms": 690.0}}})
    at(2.75)
    trace.latency("first_pcm", duration_ms=96.0, turn_id=turn_id, run_id=run_id)
    speech_start, speech_s = 2.9, 7.2
    import math
    playback_id = next(rng_ids)
    at(speech_start - 0.3)
    activity.emit_playback("pending", run_id=run_id, playback_id=playback_id)
    step = 0.08
    for i in range(int(speech_s / step)):
        at(speech_start + i * step)
        phrase = 0.55 + 0.45 * math.sin(i * 0.37) * math.sin(i * 0.11 + 1.0)
        level = max(0.0, min(1.0, phrase * (0.6 + 0.4 * math.sin(i * 1.7) ** 2)))
        if i % 22 in (20, 21):
            level = 0.02  # the gaps between sentences
        activity.emit_playback("speaking", level=round(level, 3), run_id=run_id, playback_id=playback_id)
    at(speech_start + 0.5)
    activity.emit("admission_completed", [], turn_id=turn_id)
    at(speech_start + 0.6)
    activity.emit("query_completed", packet_refs, query=QUESTION, run_id=run_id)
    answer = ("A small voice-activity model hears the pause, Smart Turn judges whether the sentence sounds "
              "finished, and the Executive starts preparing the reply before the transcript is final.")
    trace.emit("status", "Computer turn completed", [answer], {"run_id": run_id, "payload": {
        "kind": "run", "status": "completed", "task_title": "Computer", "agent_title": "Computer", "summary": answer}})
    at(speech_start + speech_s)
    activity.emit_playback("idle", run_id=run_id, playback_id=playback_id)
    trace.reset(token)
    tour["segments"].append({"view": "knowledge"})

    # Segment: the same question's history recall, shown on the Memory graph.
    base = 100.0
    at(base)
    voice = [r for r in rows if r["kind"] == "experience" and r["topic"] == "Voice"][-8:][::-1]
    activity.emit_operation("search", "returned", [hindsight.memory_ref(bank, r["id"]) for r in voice],
                            label="Memories recalled", graph_id="memory:" + bank)
    tour["segments"].append({"view": "memory", "start": base * 1000,
                             "memories": [{"text": r["text"], "type": r["kind"], "date": r["when"]} for r in voice]})

    # Segment: a coding agent's code-graph lookup, shown on the Code graph.
    base = 200.0
    at(base)
    detail = lookup_detail("search_graph", {"query": CODE_QUERY}, "Claude")
    operation_id = "claude:" + uuid.uuid5(uuid.NAMESPACE_URL, "obsidience-demo/code").hex[:28]
    activity.emit_operation("search", "running", [], label="Claude · Found", operation_id=operation_id,
                            graph_id="code:" + PROJECT, detail=detail)
    at(base + 0.9)
    names = {node["qualified_name"] for node in code["nodes"]}
    refs = ["qn:" + PROJECT + "." + name for name in CODE_RESULTS if PROJECT + "." + name in names]
    assert len(refs) >= 4, refs
    activity.emit_operation("search", "returned", refs, label="Claude · Found", operation_id=operation_id,
                            graph_id="code:" + PROJECT, detail=detail)
    tour["segments"].append({"view": "code", "start": base * 1000})

    tour["frames"], tour["trace"] = frames, entries
    tour["packet_refs"], tour["code_refs"] = packet_refs, refs
    (out / "tour.json").write_text(json.dumps(tour, separators=(",", ":")))
    print("tour", len(frames), "activity frames", len(entries), "trace entries; packet", packet_refs, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--layout", type=Path, help="a saved provider layout instead of the local provider")
    parser.add_argument("--history", default="HEAD", help="the published branch whose commits form the memory "
                        "bank (default HEAD; name the base branch while the demo's own commits are unpublished)")
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--out", type=Path, default=OUT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="obsidience-demo-") as temp:
        work = Path(temp)
        history, facts = collect_history(args.history), collect_facts(args.history)
        print("history", len(history), "commits", Counter(c["topic"] for c in history), "facts", len(facts), flush=True)
        (work / "history.json").write_text(json.dumps(history))
        (work / "facts.json").write_text(json.dumps(facts))
        layout = json.loads(args.layout.read_text()) if args.layout else fetch_layout()
        (work / "layout.json").write_text(json.dumps(public_layout(layout)))
        root = work / "root" / "obsidience"
        shutil.copytree(REPO / "obsidience" / "harness", root / "harness",
                        ignore=shutil.ignore_patterns("__pycache__"))
        # The Harness imports a few Shell modules (its command port); copy their Python only.
        shutil.copytree(REPO / "obsidience" / "shell", root / "shell",
                        ignore=lambda folder, names: [n for n in names if not n.endswith(".py")
                                                      and not (Path(folder) / n).is_dir()])
        shutil.copytree(REPO / "obsidience" / "defaults" / "vault", root / "vault")
        (root / "__init__.py").write_text("")
        subprocess.run(["unshare", "-rn", sys.executable, "-I", __file__, "--child", str(work),
                        "--out", str(args.out.resolve())], check=True)


if __name__ == "__main__":
    main()

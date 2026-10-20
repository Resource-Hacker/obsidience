"""MkDocs hook: render starter-Vault catalogue tables from Article frontmatter.

A page writes a marker such as ``<!-- catalogue:tools -->``; at build time it is
replaced by a table generated from ``obsidience/defaults/vault``. The tables are
therefore always the reviewed starter Vault's actual Agent, Task, Runbook,
Skill and Tool Articles. Unknown markers or unreadable Articles fail the build.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from mkdocs.exceptions import PluginError

VAULT = Path("obsidience/defaults/vault")
MARKER = re.compile(r"<!--\s*catalogue:([a-z]+)\s*-->")


def _articles(root: Path) -> dict[str, dict]:
    articles = {}
    for path in sorted((root / VAULT).rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        try:
            meta = yaml.safe_load(text.split("---", 2)[1]) or {}
        except yaml.YAMLError as error:
            raise PluginError(f"catalogue: cannot parse {path}: {error}") from error
        ref = path.relative_to(root / VAULT).with_suffix("").as_posix()
        articles[ref] = {"meta": meta, "obs": meta.get("obsidience") or {}}
    return articles


def _ref(value: str) -> str:
    return str(value).strip().removeprefix("[[").removesuffix("]]")


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _summary(text: object, limit: int = 200) -> str:
    """The first sentence of a catalog description; the Article holds the rest."""
    text = " ".join(str(text or "").split())
    match = re.match(r"(.+?[.!?])(?=\s+[A-Z(`]|$)", text)
    first = match.group(1) if match else text
    if len(first) > limit:
        first = first[:limit].rsplit(" ", 1)[0] + " …"
    return _cell(first)


def _render(kind: str, root: Path, repo_url: str) -> str:
    articles = _articles(root)
    blob = repo_url.rstrip("/") + "/blob/main/" + VAULT.as_posix() + "/"

    def link(ref: str) -> str:
        item = articles.get(ref)
        if item is None:
            return f"`{ref}` (missing)"
        title = item["meta"].get("title", ref)
        parts = ref.split("/")
        if parts[0] == "Tasks" and len(parts) == 3:
            title = f"{parts[1].capitalize()} / {title}"  # e.g. Generate / Runbook
        return f"[{_cell(title)}]({blob}{ref}.md)"

    def refs(values) -> str:
        values = values or []
        if isinstance(values, str):
            values = [values]
        return ", ".join(link(_ref(v)) for v in values) or "—"

    def code_names(values) -> str:
        return ", ".join(f"`{_ref(v).split('/', 1)[-1]}`" for v in values or []) or "—"

    typed = {r: a for r, a in articles.items() if a["meta"].get("type") == kind.rstrip("s")}
    if not typed:
        raise PluginError(f"catalogue: no Articles of type {kind!r} under {VAULT}")
    rows: list[str] = []
    if kind == "agents":
        rows += ["| Agent | Role | Assigned Tasks | Direct Skills | Knowledge checkouts |",
                 "| --- | --- | --- | --- | --- |"]
        for ref, a in typed.items():
            o = a["obs"]
            rows.append(f"| {link(ref)} | {_cell(o.get('role', '—'))} | {refs(o.get('tasks'))} "
                        f"| {code_names(o.get('skills'))} | {code_names(o.get('knowledge'))} |")
    elif kind == "tasks":
        rows += ["| Task | Article | Agent | Runbook | Triggers | Reasoning effort |",
                 "| --- | --- | --- | --- | --- | --- |"]
        for ref, a in typed.items():
            o = a["obs"]
            triggers = ", ".join(f"`{t}`" for t in o.get("triggers") or []) or "on request"
            rows.append(f"| {link(ref)} | `{ref}` | {refs(o.get('assignee'))} | {refs(o.get('runbook'))} "
                        f"| {triggers} | {_cell(o.get('reasoning_effort', '—'))} |")
    elif kind == "runbooks":
        rows += ["| Runbook | Article | Task | Agent | Skills |", "| --- | --- | --- | --- | --- |"]
        for ref, a in typed.items():
            o = a["obs"]
            agent = o.get("for_agent") or o.get("assignee")
            rows.append(f"| {link(ref)} | `{ref}` | {refs(o.get('task')) if o.get('task') else 'reference only'} "
                        f"| {refs(agent)} | {code_names(o.get('skills'))} |")
    elif kind == "skills":
        rows += ["| Skill | Tool | Requires | Guidance |", "| --- | --- | --- | --- |"]
        for ref, a in typed.items():
            o = a["obs"]
            rows.append(f"| {link(ref)} | {code_names([o.get('tool')])} | {code_names(o.get('requires'))} "
                        f"| {_summary(a['meta'].get('description'))} |")
    elif kind == "tools":
        rows += ["| Tool | Description | Capability source |", "| --- | --- | --- |"]
        for ref, a in typed.items():
            o = a["obs"]
            rows.append(f"| {link(ref)} | {_summary(a['meta'].get('description'))} "
                        f"| `{_cell(o.get('source', '—'))}` |")
    else:
        raise PluginError(f"catalogue: unknown catalogue {kind!r}")
    note = (f"*{len(typed)} {kind.capitalize()} Articles, generated at build time from "
            f"[`{VAULT.as_posix()}`]({repo_url.rstrip('/')}/tree/main/{VAULT.as_posix()}).*")
    return note + "\n\n" + "\n".join(rows) + "\n"


def on_page_markdown(markdown, page, config, files):
    if "catalogue:" not in markdown:
        return markdown
    root = Path(config["config_file_path"]).parent
    repo_url = config["repo_url"]
    return MARKER.sub(lambda m: _render(m.group(1), root, repo_url), markdown)

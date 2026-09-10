"""Adapter for ``vault.validate``."""

from __future__ import annotations

from collections import Counter

import yaml


def execute(args: dict, context: dict) -> str:
    del args, context
    from obsidience.harness.capabilities.registry import REGISTRY, contract_error
    from obsidience.harness.config import CONFIG
    from obsidience.harness.knowledge.format import parse, validate_profile
    from obsidience.harness.knowledge.skills import (
        build_skill_mirror,
        node_id as skill_mirror_node_id,
    )
    from obsidience.harness.knowledge.tasks import (
        CANONICAL_TASK_BY_PATH,
        TASK_TAXONOMY_BY_PATH,
        task_triggers,
    )
    from obsidience.harness.knowledge.vault import (
        CHILD_FIELD_BY_KIND,
        HIERARCHY_FIELDS,
        SOURCE_DIRS,
        SYSTEM_DIRS,
        iter_notes,
        resolver,
    )

    # Validate persisted bytes, not a re-encoded runtime projection: projection
    # would hide misplaced fields and Task state that must not live in Articles.
    profile_errors: list[str] = []
    profiles_checked = 0
    for path in sorted(CONFIG.vault_dir.rglob("*.md")):
        relative = path.relative_to(CONFIG.vault_dir)
        if relative.parts[0] in (*SOURCE_DIRS, *SYSTEM_DIRS) or any(
            part.startswith(".") for part in relative.parts
        ):
            continue
        try:
            raw, _ = parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
            profile_errors.append(f"- [[{relative.with_suffix('')}]] OKF profile: {error}")
            continue
        if path.name.lower() in {"index.md", "log.md"} and not ({"type", "kind"} & raw.keys()):
            continue  # Ordinary OKF navigation/history is not an Article.
        profiles_checked += 1
        profile_errors.extend(
            f"- [[{relative.with_suffix('')}]] OKF profile: {error}"
            for error in validate_profile(raw, relative)
        )
    if profile_errors:
        return (
            f"{profiles_checked} Article profiles checked, {len(profile_errors)} invalid:\n"
            + "\n".join(profile_errors[:30])
        )

    res = resolver()
    notes = iter_notes()
    taxonomy_path_by_ref = {
        ref: path for path, ref in CANONICAL_TASK_BY_PATH.items()
    }

    def task_path(note) -> str:
        return str(note.meta.get("taxonomy_path") or taxonomy_path_by_ref.get(note.ref, ""))

    def exclusion_path(raw_ref: str) -> str:
        if raw_ref.startswith("@library/Tasks/"):
            path = raw_ref.removeprefix("@library/Tasks/")
            return path if path in TASK_TAXONOMY_BY_PATH else ""
        target = res.resolve(raw_ref)
        return task_path(target) if target and target.kind == "task" else ""

    skill_mirror_refs = {
        skill_mirror_node_id(node.path) for node in build_skill_mirror(notes)
    }
    broken, checked = [], 0
    for note in notes:
        if str(note.meta.get("kind", "")).strip().lower() == "index":
            broken.append(
                f"- [[{note.ref}]] kind: index (index behavior is derived from children)"
            )
        for field in ("runbook", *HIERARCHY_FIELDS, "skills", "exclude_subtasks"):
            value = note.meta.get(field)
            for ref in (
                value if isinstance(value, list) else [value] if value else []
            ):
                checked += 1
                raw_ref = (
                    str(ref).strip().strip("[]").split("|", 1)[0].split("#", 1)[0]
                )
                if field == "skills" and raw_ref in skill_mirror_refs:
                    continue
                if field == "exclude_subtasks" and raw_ref.startswith("@library/Tasks/"):
                    root_path = task_path(note) if note.kind == "task" else ""
                    path = exclusion_path(raw_ref)
                    if not root_path or not path.startswith(root_path + "/"):
                        broken.append(
                            f"- [[{note.ref}]] {field}: {ref} (expected task descendant)"
                        )
                    continue
                target = res.resolve(str(ref))
                if not target:
                    broken.append(f"- [[{note.ref}]] {field}: {ref} (unresolved)")
                elif field == CHILD_FIELD_BY_KIND.get(note.kind) and target.kind != note.kind:
                    broken.append(
                        f"- [[{note.ref}]] {field}: {ref} "
                        f"(expected {note.kind}, got {target.kind})"
                    )
                elif field == "exclude_subtasks" and (
                    note.kind != "task" or target.kind != "task"
                ):
                    broken.append(
                        f"- [[{note.ref}]] {field}: {ref} (expected task descendant)"
                    )
        if note.kind == "runbook" and note.meta.get("tools"):
            broken.append(
                f"- [[{note.ref}]] tools: direct Tool grants are not allowed; "
                "use paired Skills"
            )

    tool_articles = [note for note in notes if note.kind == "tool"]
    leaf_tools = [note for note in tool_articles if not note.children]
    for tool in (note for note in tool_articles if note.children):
        checked += 1
        if tool.meta.get("binding") or tool.meta.get("source"):
            broken.append(
                f"- [[{tool.ref}]] executable metadata: Tool index Articles cannot "
                "carry a binding or source"
            )
    skills_by_tool: dict[str, list[str]] = {tool.ref: [] for tool in leaf_tools}
    for skill in (note for note in notes if note.kind == "skill"):
        if skill.meta.get("tools"):
            broken.append(f"- [[{skill.ref}]] tools: plural Tool fields are not allowed")
        if skill.children:
            checked += 1
            if skill.meta.get("tool"):
                broken.append(
                    f"- [[{skill.ref}]] tool: Skill index Articles cannot carry a pairing"
                )
            continue
        refs = [skill.meta.get("tool")] if skill.meta.get("tool") else []
        checked += 1
        if len(refs) != 1:
            broken.append(f"- [[{skill.ref}]] tool: exactly one Tool is required")
            continue
        target = res.resolve(str(refs[0]))
        if not target or target.kind != "tool" or target.children:
            actual = target.kind if target else "unresolved"
            broken.append(
                f"- [[{skill.ref}]] tool: {refs[0]} (expected leaf tool, got {actual})"
            )
            continue
        skills_by_tool.setdefault(target.ref, []).append(skill.ref)

    leaf_titles: list[str] = []
    for tool in leaf_tools:
        checked += 1
        leaf_titles.append(tool.title)
        # OKF sources is provenance. Only singular obsidience.source binds the
        # executable entrypoint, which still must match the registry exactly.
        error = contract_error(
            tool.title,
            tool.meta.get("binding"),
            tool.meta.get("source"),
        )
        if error:
            broken.append(f"- [[{tool.ref}]] Capability contract: {error}")
        paired = skills_by_tool.get(tool.ref, [])
        if len(paired) != 1:
            broken.append(
                f"- [[{tool.ref}]] paired Skill: expected 1, found {len(paired)}"
                + (f" ({', '.join(paired)})" if paired else "")
            )

    for title, count in sorted(Counter(leaf_titles).items()):
        if count != 1:
            broken.append(f"- Tool title {title}: expected one leaf Article, found {count}")
    missing_tools = sorted(set(REGISTRY) - set(leaf_titles))
    if missing_tools:
        broken.append(
            "- Capability registry entries without leaf Tool Articles: "
            + ", ".join(missing_tools)
        )

    reported_cycles: set[frozenset[str]] = set()
    for kind in CHILD_FIELD_BY_KIND:
        visited: set[str] = set()
        active: list[str] = []

        def visit(note):
            if note.ref in active:
                cycle = active[active.index(note.ref):] + [note.ref]
                key = frozenset(cycle)
                if key not in reported_cycles:
                    reported_cycles.add(key)
                    broken.append(f"- {kind} hierarchy cycle: {' -> '.join(cycle)}")
                return
            if note.ref in visited:
                return
            active.append(note.ref)
            for raw in note.children:
                child = res.resolve(raw)
                if child and child.kind == kind:
                    visit(child)
            active.pop()
            visited.add(note.ref)

        for root in (note for note in notes if note.kind == kind):
            visit(root)

    for task in (note for note in notes if note.kind == "task"):
        reachable: set[str] = set()
        pending = list(task.children)
        while pending:
            child = res.resolve(pending.pop(0))
            if not child or child.kind != "task" or child.ref in reachable:
                continue
            reachable.add(child.ref)
            pending.extend(child.children)
        excluded = task.meta.get("exclude_subtasks") or []
        for raw in excluded if isinstance(excluded, list) else [excluded]:
            raw_ref = (
                str(raw).strip().strip("[]").split("|", 1)[0].split("#", 1)[0]
            )
            target = res.resolve(str(raw))
            path = exclusion_path(raw_ref)
            root_path = task_path(task)
            taxonomy_descendant = bool(
                root_path and path and path.startswith(root_path + "/")
            )
            if (
                target
                and target.kind == "task"
                and target.ref not in reachable
                and not taxonomy_descendant
            ):
                broken.append(
                    f"- [[{task.ref}]] exclude_subtasks: {raw} (not a descendant)"
                )

    reserved_source_events = {
        "source.added": ({"Tasks/research/learn", "Tasks/research/distill"}, "Agents/Darwin/Darwin"),
        "source.inbox": ({"Tasks/ingest"}, "Agents/Alexandria/Alexandria"),
    }
    tasks = [note for note in notes if note.kind == "task"]
    for event, (expected_tasks, expected_agent) in reserved_source_events.items():
        checked += 1
        subscribers = [
            note for note in tasks
            if event in task_triggers(note.meta)
            and note.meta.get("enabled", True) is not False
            and str(note.meta.get("enabled", True)).strip().lower()
            not in {"0", "false", "no", "off"}
        ]
        if {note.ref for note in subscribers} != expected_tasks:
            broken.append(
                f"- {event} subscribers: expected "
                + ", ".join(f"[[{ref}]]" for ref in sorted(expected_tasks)) + ", found "
                + (", ".join(f"[[{note.ref}]]" for note in subscribers) or "none")
            )
            continue
        for subscriber in subscribers:
            assignee = res.resolve(str(subscriber.meta.get("assignee", "")))
            if not assignee or assignee.ref != expected_agent:
                broken.append(
                    f"- [[{subscriber.ref}]] assignee: expected [[{expected_agent}]]"
                )
    if not broken:
        return f"All {checked} load-bearing edges resolve. No broken references."
    return f"{checked} edges checked, {len(broken)} broken:\n" + "\n".join(broken[:30])

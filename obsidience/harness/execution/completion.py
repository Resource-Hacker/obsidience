"""Acceptance policy for the executor-owned ``task.complete`` terminal decision.

Computer-operation witnesses, unsupported effect claims, staged-proposal
states, evidence citations and the Tools offered before a terminal decision.
The ``task.complete`` adapter validates its arguments and applies this policy.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import unicodedata

from obsidience.harness.computer.applications import canonical_application_id

COMPUTER_OUTCOME_TOOLS = {
    "media": "media.pause",
    "focus": "window.activate",
    "placement": "window.place",
    "observe": "computer.observe",
    "action": "computer.act",
    "launch": "application.launch",
    "unlock": "session.unlock",
}


def validate_computer_outcome(outcome: object, scope: object = None) -> str | None:
    """Validate a controller binding without classifying request prose."""
    if outcome is None or outcome == "" or outcome == "answer":
        return None if scope is None or scope == "" else "an answer cannot carry a computer scope"
    if not isinstance(outcome, str) or outcome not in COMPUTER_OUTCOME_TOOLS:
        return "the controller's requested computer outcome is invalid"
    if outcome == "action":
        if not isinstance(scope, str) or scope not in {"input", "state"}:
            return "an action requires an explicit computer_scope of input or state"
    elif scope is not None and scope != "":
        return "computer_scope applies only to an action outcome"
    return None


def _computer_target(value: object) -> dict | None:
    """Keep only the Tool's bounded public identity, never private window IDs."""
    if not isinstance(value, dict):
        return None
    kind, name = value.get("kind"), value.get("name")
    if (
        kind not in ("application", "pane", "session")
        or not isinstance(name, str)
        or not name
        or len(name) > (256 if kind == "application" else 48)
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        return None
    if kind == "application":
        name = canonical_application_id(name) or name
    return {"kind": kind, "name": name}


def computer_request_target_error(name: str, args: dict, context: dict) -> str | None:
    """Reject an explicit contradiction of the controller's application binding.

    Missing/malformed arguments remain with the Capability's own validator.
    A focused observation may resolve normally; acceptance checks its witness.
    """
    if name not in COMPUTER_OUTCOME_TOOLS.values():
        return None
    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    if not params.get("application"):
        return None
    binding = _computer_target({"kind": "application", "name": params["application"]})
    if binding is None:
        return "The controller's requested application binding is invalid."
    application = binding["name"]
    if name in {"application.launch", "computer.act"}:
        target = _computer_target({"kind": "application", "name": args.get("application")})
    else:
        target = _computer_target(args.get("target"))
    if target is None or target == {"kind": "application", "name": application}:
        return None
    return (
        f"The explicit Tool target contradicts the requested application {application}. "
        "Nothing was dispatched. Correct the target using that canonical binding; "
        "do not substitute another application or pane."
    )


def computer_completion_evidence(
    name: str, result: dict | None, *, image_attached: bool = False,
) -> dict | None:
    """Project a real Tool result for acceptance, before trace text is truncated.

    Only the executor calls this after dispatch. Model-authored summary and
    evidence strings cannot substitute for this bounded controller witness.
    """
    if name not in COMPUTER_OUTCOME_TOOLS.values():
        return None
    result = result or {}
    target = _computer_target(result.get("target"))
    verified = False
    effect = None
    if name == "media.pause":
        target = {"kind": "application", "name": "microsoft_edge"}
        verified = (result.get("status") == "completed" and result.get("delivery") == "verified"
                    and result.get("state") in {"Paused", "Stopped"})
    elif name == "session.unlock":
        target = {"kind": "session", "name": "desktop"}
        verified = (result.get("status") == "completed" and result.get("locked") is False
                    and result.get("delivery") == "acknowledged")
    elif name == "window.activate":
        verified = result.get("status") == "completed" and result.get("active") is True
    elif name == "window.place":
        destination = result.get("destination") or {}
        observed = result.get("observed") or {}
        verified = (
            result.get("status") == "completed"
            and isinstance(destination, dict)
            and isinstance(observed, dict)
            and bool(destination.get("surface"))
            and observed.get("surface") == destination.get("surface")
            and (
                "tile" not in destination
                or (
                    isinstance(destination["tile"], dict)
                    and set(destination["tile"]) == {"left", "top", "right", "bottom"}
                    and all(type(value) is int for value in destination["tile"].values())
                    and isinstance(observed.get("tile"), dict)
                    and all(type(value) is int for value in observed["tile"].values())
                    and observed["tile"] == destination["tile"]
                )
            )
        )
    elif name == "application.launch":
        target = _computer_target({"kind": "application", "name": result.get("application")})
        verified = (
            result.get("state") == "ready"
            and result.get("ready") is True
            and isinstance(result.get("window"), dict)
            and bool(result["window"])
        )
    elif name == "computer.observe":
        observation = result.get("observation") or {}
        target = _computer_target(observation.get("target")) if isinstance(observation, dict) else None
        visual = (
            observation.get("visual_evidence") or {}
            if isinstance(observation, dict) else {}
        )
        verified = (
            isinstance(observation, dict)
            and observation.get("status") == "observed"
            and isinstance(visual, dict)
            and visual.get("freshness") == "validated_after_capture"
            and visual.get("attached") is True
            and image_attached
        )
    elif name == "computer.act":
        observed = result.get("observation")
        clicked = result.get("effect")
        visual = observed.get("visual_evidence") if isinstance(observed, dict) else None
        label = clicked.get("label") if isinstance(clicked, dict) else None
        verified = (
            result.get("status") == "completed"
            and result.get("delivery") == "acknowledged"
            and isinstance(clicked, dict)
            and clicked.get("kind") == "click"
            and clicked.get("verified") is True
            and isinstance(label, str)
            and 0 < len(label) <= 300
            and bool(label.strip())
            and not any(ord(character) < 32 or ord(character) == 127 for character in label)
            and target is not None
            and target["kind"] == "application"
            and isinstance(observed, dict)
            and observed.get("status") == "observed"
            and _computer_target(observed.get("target")) == target
            and observed["target"].get("surface") == result["target"].get("surface")
            and isinstance(visual, dict)
            and visual.get("freshness") == "validated_after_capture"
            and visual.get("attached") is True
            and image_attached
        )
        if verified:
            # This witnesses the grounded click, never the optional semantic
            # postcondition suggested in the model's Tool arguments.
            effect = {"kind": "click", "label": _normalized_click_text(label)}
    return {
        "verified": bool(verified and target),
        **({"target": target} if target else {}),
        **({"effect": effect} if effect else {}),
        **({"launch_outcome": result["wait_status"]}
           if name == "application.launch" and result.get("wait_status") in {
               "terminated_before_ready", "timeout", "launcher_timeout",
           } else {}),
        **({"verified_scope": "click", "semantic_postcondition_verified": False} if effect else {}),
    }


def _normalized_click_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _refused_before_dispatch(item: dict) -> bool:
    """The executor refused this call's target; no operation was attempted."""
    try:
        result = json.loads(item.get("obs") or "")
    except (TypeError, ValueError):
        return False
    return (isinstance(result, dict) and result.get("delivery") == "not_dispatched"
            and (result.get("failure") or {}).get("code") == "controller_target_mismatch")


def _latest_computer_results(context: dict) -> dict:
    latest = {}
    for item in context.get("trace", []):
        if not isinstance(item, dict) or item.get("tool") not in COMPUTER_OUTCOME_TOOLS.values():
            continue
        if _refused_before_dispatch(item):
            continue
        if item["tool"] == "computer.observe":
            # Observation is a read of current state, not a retained effect.
            # A fresh read can recover from lock or target ambiguity. Actual
            # actions below remain independently bound to their exact targets.
            latest[("computer.observe", "current")] = item
            continue
        args = item.get("args") or {}
        target = (args.get("query", "") if item["tool"] == "media.pause" else
                  args.get("application") or args.get("target") or {})
        if isinstance(target, dict):
            target = tuple((key, target.get(key)) for key in ("kind", "name", "surface", "title"))
        latest[(item["tool"], str(target))] = item
    return latest


def native_text_arguments(text: str, context: dict) -> dict:
    """Derive terminal state from controller findings, not the LLM stop token.

    A failed observation remains a failed operation even when the model explains
    the blocker in ordinary text. State verification still requires the native
    completion Tool; this helper cannot infer a visual postcondition.
    """
    status = "completed"
    if any((item.get("completion_evidence") or {}).get("verified") is not True
           for item in _latest_computer_results(context).values()):
        status = "failed"
    if context.get("_tv_control_failed") or context.get("_media_acquire_failed"):
        status = "failed"
    if _pending_staged_proposals(context):
        status = "review"
    return {"status": status, "summary": text}


def _unlock_claim_error(summary: str, context: dict) -> str | None:
    """Reject a positive desktop-unlock claim without this run's native receipt.

    This checks a reported effect, never routes requests or dispatches an action.
    Quoted examples and explanations do not match a standalone success clause.
    """
    claim = re.search(
        r"(?:^|[.!?]\s+)(?:i(?: have|'ve)?(?: now| just| successfully)? unlocked "
        r"(?:the |your )?(?:computer|desktop|session|screen)\b|"
        r"(?:the |your )?(?:computer|desktop|session|screen) "
        r"(?:is|has been|is now|is already) unlocked\b)", summary, re.I,
    )
    if not claim:
        return None
    if any(item.get("tool") == "session.unlock"
           and (item.get("completion_evidence") or {}).get("verified") is True
           for item in _latest_computer_results(context).values()):
        return None
    return ("No verified session.unlock receipt exists in this execution. Do not report the desktop "
            "unlocked from an earlier reply. If the current owner request asks for unlock, call "
            "session.unlock with {} once and use its result; otherwise answer without claiming an unlock. "
            "Never repeat failed or uncertain delivery.")


_RECAP = re.compile(r"\b(?:earlier|previously|before|last time|a moment ago|in (?:the|my) previous)\b", re.I)
# Each first-person effect claim needs its own verified receipt in this run.
_EFFECT_CLAIMS = (
    (re.compile(r"(?:^|[.!?]\s+)i(?: have|'ve)?(?: now| just| successfully| already)? "
                r"(?:pulled up|opened|re-?opened|launched|brought up|loaded|navigated to)\b", re.I),
     {"application.launch", "window.activate", "computer.act"},
     "No verified application.launch, window.activate or computer.act result exists in this execution. "
     "Do not report opening or pulling something up from an earlier reply. If the current owner request "
     "asks for it, call application.launch now (with url for a web page) and use its result; to report "
     "what is already showing, call computer.observe. Otherwise answer without claiming the action."),
    (re.compile(r"(?:^|[.!?]\s+)i(?: have|'ve)?(?: now| just| successfully| already)? (?P<media_action>paused|stopped) "
                r"(?:the |your |that |this )?(?:video|music|song|track|playback|media|youtube|it)\b", re.I),
     {"media.pause"},
     "No verified media.pause result exists in this execution. Do not report pausing from an earlier "
     "reply. If the current owner request asks to pause or stop media, call media.pause and use its "
     "result; otherwise answer without claiming the action."),
)


def _discord_media_claim_verified(claim: str, context: dict) -> bool:
    """Use this run's complete transport receipt, not truncated trace text."""
    for encoded_args, receipt in reversed(list(context.get("_discord_control_attempts", {}).items())):
        action = json.loads(encoded_args).get("action")
        if action not in {"play", "pause", "resume", "stop", "leave"}:
            continue
        # A later playback/resume or failed effect invalidates an earlier stop.
        expected = "stop" if claim == "stopped" else "pause"
        return (action == expected and receipt.get("ok") is True
                and receipt.get("status") == "completed"
                and receipt.get("playback") == ("idle" if expected == "stop" else "paused")
                and not receipt.get("must_not_replay"))
    return False


def _effect_claim_error(summary: str, context: dict) -> str | None:
    """Reject a reported open/pause effect without this run's verified receipt.

    Like the unlock check, this inspects a claim only; it never routes or acts.
    A sentence recapping earlier work remains an ordinary historical answer.
    """
    verified = {item["tool"] for item in _latest_computer_results(context).values()
                if (item.get("completion_evidence") or {}).get("verified") is True}
    for pattern, tools, message in _EFFECT_CLAIMS:
        for claim in pattern.finditer(summary):
            sentence = re.split(r"[.!?]", summary[claim.start():].lstrip(".!? "), maxsplit=1)[0]
            if not _RECAP.search(sentence) and not tools & verified:
                action = claim.groupdict().get("media_action")
                if action and _discord_media_claim_verified(action, context):
                    continue
                if action and context.get("_discord"):
                    return ("No current verified Discord pause/stop receipt supports this claim. "
                            "Use discord.control only if the current request calls for that action; "
                            "never replay failed or uncertain delivery or restart rejected media.")
                return message
    return None


# A direction must end its clause, so "I looked up the weather" or "turned up the
# volume" is not a camera turn.
_CAMERA_DIRECTION = (r"(?:down(?:wards?)?|up(?:wards?)?|left|right|lower|higher|to the (?:left|right))"
                     r"(?=\s*(?:[,.;:!?]|$)|\s+(?:and|but|so|to|toward|towards|at|again|further|more|now|"
                     r"a bit|slightly|as|for)\b)")
_CAMERA_TURN_CLAIM = re.compile(
    r"(?:^|[.!?]\s+)(?:i(?: have|['’]ve)?(?: now| just| already| also)? "
    r"(?:looked|turned|moved|tilted|panned|pointed|angled|aimed)(?: the camera)?"
    r"(?: further| a bit| slightly)? " + _CAMERA_DIRECTION + "|"
    r"i(?: have|['’]ve)?(?: now| just| already| also)? (?:turned|moved|tilted|panned|pointed|angled|aimed) "
    r"the camera\b(?!\s+(?:back\s+)?(?:on|off)\b)|the camera (?:has |is now |is )?(?:turned|moved|tilted|panned|looking|pointing) "
    + _CAMERA_DIRECTION + ")", re.I)


def _camera_turn_claim_error(summary: str, context: dict) -> str | None:
    """Reject a reported camera turn without this run's camera.observe look call.

    Like the other claim checks, this inspects the claim only; it never maps a
    query to a look direction or dispatches a call.
    """
    # A look counts only when it returned a camera observation without a failure;
    # a Tool error, an interrupted or an undispatched call proves no turn.
    looked = any(
        item.get("tool") == "camera.observe" and (item.get("args") or {}).get("look")
        and not (item.get("interrupted") or item.get("not_dispatched") or item.get("must_not_replay"))
        and str(item.get("obs") or "").startswith('{"observation"')
        and '"failure"' not in str(item.get("obs") or "")
        for item in context.get("trace", []) if isinstance(item, dict))
    if looked:
        return None
    for claim in _CAMERA_TURN_CLAIM.finditer(summary):
        sentence = re.split(r"[.!?]", summary[claim.start():].lstrip(".!? "), maxsplit=1)[0]
        if not _RECAP.search(sentence):
            return ("No camera.observe call with look ran in this execution, so the camera has not turned. "
                    "Do not say you looked or turned it. If what was asked about is cut off by an edge or the "
                    "owner named a direction, call camera.observe with the visual question as query and look "
                    "set to left, right, up or down, then answer from that picture.")
    return None


def public_claim_error(summary: str, context: dict) -> str | None:
    """The Executive completion's unsupported unlock/effect claim check.

    Early voice playback applies the same check to each sentence before it
    is spoken; it inspects text only and never routes or acts.
    """
    if context.get("_tv_control_failed") and re.search(
            r"\b(?:I(?:['’]ll| will)|we(?:['’]ll| will))\s+(?:try|retry|reconnect|check|keep trying).*\b(?:again|later|moment|shortly|soon|now|find)\b",
            summary, re.I):
        return "TV control failed and no retry is scheduled. Report the current blocker without promising a later action."
    if context.get("_tv_control_failed") and re.search(
            r"\b(?:successfully|started playing|is (?:now )?playing)\b", summary, re.I) and not re.search(
            r"\b(?:cannot|can't|couldn't|unable|unverified|uncertain|not verified)\b", summary, re.I):
        return "TV verification failed. State that the requested outcome could not be verified; do not report unqualified playback success."
    return (_unlock_claim_error(summary, context) or _effect_claim_error(summary, context)
            or _camera_turn_claim_error(summary, context))


def _computer_completion_error(task, status: str, context: dict, verification=None) -> str | None:
    """Attest actual computer operations for every Task with these Tools.

    Legacy explicit outcome bindings remain enforceable. Ordinary Executive
    runs acquire their operation/scope from real Tool decisions, not admission.
    A different successful Tool cannot erase a failed or uncertain operation.
    """
    if context.get("_tv_control_failed") and status != "failed":
        return "TV control failed in this run; finish with status failed and the actual blocker."
    if context.get("_media_acquire_failed") and status != "failed":
        return "Media registration failed or is uncertain; finish failed with its receipt and do not replay."
    if status != "completed":
        return None
    if context.get("_tv_navigation_applied") and (not verification or verification["status"] != "established"):
        return "TV input delivery is not outcome verification. Use task.complete with verification status established and current title/player or requested screen evidence; otherwise finish failed with the actual blocker."
    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    outcome, scope = params.get("computer_outcome", ""), params.get("computer_scope")
    if invalid := validate_computer_outcome(outcome, scope):
        return invalid
    expected = COMPUTER_OUTCOME_TOOLS.get(outcome)
    latest = _latest_computer_results(context)
    if expected and not any(item["tool"] == expected for item in latest.values()):
        return f"Completion requires a verified result from {expected} in this execution."
    # A fresh result can settle the same target; a different target cannot hide it.
    for item in latest.values():
        name, witness = item["tool"], item.get("completion_evidence")
        if not (isinstance(witness, dict) and witness.get("verified") is True
                and _computer_target(witness.get("target")) is not None):
            return (f"Completion requires a verified result from {name} for its requested target. "
                    "Report the actual blocker with status failed; never replay uncertain delivery.")
        application = params.get("application")
        if application and witness["target"] != _computer_target({"kind": "application", "name": application}):
            return "The verified result does not match the explicitly bound application; do not claim completion."
        if name == "application.launch" and (item.get("args") or {}).get("url"):
            current = context.get("_computer_response_observation")
            if not (isinstance(current, dict) and current.get("verified") is True
                    and _computer_target(current.get("target")) == witness["target"]):
                return ("No current post-URL image is available for this completion. An earlier image was "
                        "already consumed, including by any rejected completion. Call computer.observe again "
                        "on the browser, then task.complete with verification status established and the "
                        "visible evidence, or finish failed with the actual blocker. Do not reopen the URL.")
            if not verification or verification["status"] != "established":
                return ("Browser page or playback state requires task.complete verification with status "
                        "established and observation describing the visible evidence. This rejected completion "
                        "consumed its image: observe again before completing, or finish failed. Do not reopen the URL.")
        if name != "computer.act":
            continue
        effect = witness.get("effect")
        if not (witness.get("verified_scope") == "click"
                and witness.get("semantic_postcondition_verified") is False
                and isinstance(effect, dict) and effect.get("kind") == "click"
                and isinstance(effect.get("label"), str) and effect["label"]):
            return "Input completion requires an acknowledged intended click with a fresh post-image."
        action_scope = (item.get("args") or {}).get("scope", scope)
        if action_scope not in {"input", "state"}:
            return "The computer action has no valid input/state scope."
        if action_scope == "state":
            current = context.get("_computer_response_observation")
            if not (isinstance(current, dict) and current.get("verified") is True
                    and _computer_target(current.get("target")) == witness["target"]):
                return ("The requested application state requires its actual fresh post-action image "
                        "in this completion response for the same action and target; historical evidence cannot establish it.")
            if not verification or verification["status"] != "established":
                return ("Application state requires verification with status established and an observation "
                        "describing the visible evidence; otherwise finish failed without replaying input.")
    return None


def staged_proposal_states(context: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Return pending, approved, and rejected controller-bound proposals."""
    from obsidience.harness.config import CONFIG
    from obsidience.harness.knowledge.index import INDEX

    pending: list[dict] = []
    approved: list[dict] = []
    rejected: list[dict] = []
    for item in context.get("staged_proposals") or []:
        if not isinstance(item, dict):
            continue
        if item.get("auto_approved") is True:
            approved.append(item)
            continue
        staged = str(item.get("staged", "")).strip()
        if not staged:
            pending.append(item)
            continue
        path = Path(staged)
        if not path.is_absolute():
            path = CONFIG.vault_dir / path
        if path.is_file():
            pending.append(item)
            continue
        decision = INDEX.review_decision(Path(staged).name)
        if not decision or any(
            decision.get(key) != value
            for key, value in {
                "run_id": str(context.get("run_id", "")),
                "task_ref": str(context.get("task", "")),
                "target": str(item.get("target", "")),
            }.items()
        ):
            pending.append(item)
        elif decision["decision"] == "approved":
            approved.append(item)
        else:
            rejected.append(item)
    return pending, approved, rejected


def _pending_staged_proposals(context: dict) -> list[dict]:
    return staged_proposal_states(context)[0]


def _generated_runbook_completion_error(status: str, context: dict) -> str | None:
    if context.get("event") != "task.assigned":
        return None
    params = context.get("params")
    if not isinstance(params, dict):
        return "Runbook generation is missing assignment event parameters"
    expected = str(params.get("output_runbook", "")).strip()
    staged = _pending_staged_proposals(context)
    matched = any(
        isinstance(item, dict)
        and item.get("target") == expected
        and item.get("action") in {"create", "update"}
        for item in (staged if isinstance(staged, list) else [])
    )
    if matched and status != "review":
        return 'a staged Runbook must finish with status "review"'
    if not matched and status != "failed":
        return (
            f"no validated proposal for {expected or '(missing output path)'} was staged "
            'during this execution; call vault.propose, then finish with status "review"'
        )
    return None


def evidence_bound_completion(task_ref: str, context: dict) -> bool:
    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    return bool(
        context.get("maintenance_candidate")
        or context.get("event") == "observations.memory.ready"
        or (
            task_ref == "Tasks/ingest"
            and context.get("event") == "source.inbox"
        )
        or (
            task_ref in {"Tasks/research/question", "Tasks/research/learn"}
            and params.get("created_by_run_id")
            and not context.get("handoff_source_id")
        )
    )


def completion_requires_no_change(context: dict) -> bool:
    """Narrow successful completion syntax from current controller-owned state."""
    return (evidence_bound_completion(str(context.get("task", "")), context)
            and not any(staged_proposal_states(context)))


def completion_prerequisite_error(context: dict) -> str | None:
    """Project existing evidence requirements before offering successful completion."""
    from obsidience.harness.capabilities.source.read import bound_read_error

    if error := bound_read_error(context):
        return error
    if context.get('task') == 'Tasks/audit' and context.get('_harness_optimization_attempted'):
        case_id = (context.get('params') or {}).get('optimization_case')
        report = context.get('_harness_optimization')
        if not case_id or not isinstance(report, dict) or report.get('case_id') != case_id or not report.get('report_id'):
            return 'Optimization returned no bound report; finish failed with the actual Tool blocker'
    if (context.get("event") == "observations.memory.ready"
            and not context.get("_vault_searches")):
        return "Curate no-change requires a successful Knowledge search for the bound Source's topics"
    return None


def completion_citations(context: dict) -> list[str] | None:
    """What a successful Curate inspection may cite: its Source and each Article read in full.

    The step's evidence schema offers only these, so a search lead read in part
    or not at all cannot be cited (Curate's recurring rejection, 2026-10-13).
    """
    if context.get("event") != "observations.memory.ready":
        return None
    from obsidience.harness.capabilities.source.read import required_source
    from obsidience.harness.knowledge.source import SourceError
    from obsidience.harness.knowledge.vault import load_note

    try:
        source = required_source(context)
    except SourceError:
        return None
    if not source:
        return None
    citations = [source["citation"]]
    for ref, read in sorted(context.get("_article_reads", {}).items()):
        note = load_note(ref + ".md") if isinstance(read, dict) and read.get("complete") is True else None
        if note is not None and read.get("article_sha256") == hashlib.sha256(note.text().encode()).hexdigest():
            citations.append(f"[[{ref}]]")
    return citations


def completion_error(
    task,
    status: str,
    outcome: str,
    evidence: list[str],
    context: dict,
    verification=None,
) -> str | None:
    from obsidience.harness.capabilities.source.read import bound_read_error, required_source

    if status != "failed" and context.get("event") == "observations.memory.ready":
        from obsidience.harness.memory.hindsight import promotion_source
        source = promotion_source({**(context.get("params") or {}),
                                   "origin_task_ref": context.get("task"), "event": context.get("event")})
        receipt = context.get("_source_reads", {}).get(source["citation"], {})
        if (receipt.get("content_sha256") != source["content_sha256"]
                or [0, len(source["content"])] not in receipt.get("ranges", [])):
            return "Read the complete bound Hindsight Source before completing Curate"
        if status == "completed" and outcome != "no_change" and context.get("_memory_proposal_rejection"):
            return "The memory recommendation remains rejected; correct it or finish failed: " + context["_memory_proposal_rejection"]
        if status == "completed" and source["citation"] not in "\n".join(evidence):
            return "Curate no-change evidence must cite the exact Hindsight Source"
        if status == "completed":
            searches = context.get("_vault_searches", {})
            if error := completion_prerequisite_error(context):
                return error
            from obsidience.harness.knowledge.vault import resolver
            from obsidience.harness.knowledge.scope import execution_scope
            res = resolver()
            _agent, allowed = execution_scope(context, res)
            cited = "\n".join(evidence)
            # Retrieval offers leads; it does not establish their relevance.
            # Require full reads for Articles claimed as no-change evidence,
            # not an arbitrary search hit that the curator found unrelated.
            # An approved change cites its publication receipt; that approval
            # itself made the earlier read of its target stale.
            candidates = {ref: res.resolve(ref) for row in searches.values()
                          for ref in row.get("refs", []) if ref in cited} if outcome == "no_change" else {}
            candidates = {ref: note for ref, note in candidates.items()
                          if note and note.kind == "knowledge" and ref in allowed
                          and not ref.startswith("Agents/") and not note.runtime_observation}
            if candidates:
                reads = context.get("_article_reads", {})
                calls = []
                for ref, note in candidates.items():
                    read = reads.get(ref, {})
                    current = read.get("article_sha256") == hashlib.sha256(note.text().encode()).hexdigest()
                    if current and read.get("complete") is True:
                        continue
                    start, end = (read.get("ranges") or [[None, None]])[0]
                    # Name the exact next call, in the advertised argument order.
                    if current and start == 0 and read.get("view_sha256"):
                        calls.append(f"{ref} is read to character {end} of {read.get('total_characters')}: vault.read "
                                     + json.dumps({"ref": ref, "offset": end, "expected_sha256": read["view_sha256"]},
                                                  ensure_ascii=False))
                    else:
                        calls.append(f"{ref} has no read of its current text: vault.read "
                                     + json.dumps({"ref": ref}, ensure_ascii=False))
                if calls:
                    return ("Curate evidence cites an Article without a complete current read. "
                            "Finish reading each cited Article, or omit it if the search lead was unrelated: "
                            + "; ".join(calls) + ". no-change may cite the bound Hindsight Source; "
                            "explain why no recommendation is useful in summary, not in evidence.")
            for item in context.get("trace", []):
                if item.get("tool") != "task.create" or item.get("not_dispatched"):
                    continue
                try:
                    result = json.loads(item.get("obs", ""))
                except (TypeError, ValueError):
                    continue
                if isinstance(result, dict) and result.get("state") in {"started", "queued", "processed"}:
                    return "An unrelated maintenance delegation cannot complete this Hindsight curation; report the scope failure"
    if status != "failed":
        if error := bound_read_error(context):
            return error
        bound = required_source(context)
        if (bound and task.ref == "Tasks/research/learn"
                and status == "completed" and not context.get("handoff_source_id")):
            citation = bound["citation"]
            from obsidience.harness.knowledge.source import SourceError, validate_source_citations

            try:
                citations = validate_source_citations("\n".join(evidence), required=True)
            except (SourceError, OSError) as exc:
                return "Source-bound Learn completion evidence is invalid: " + str(exc)
            if outcome != "no_change" or not any(
                item["citation"] == citation and item["content_sha256"] == bound["content_sha256"]
                for item in citations
            ):
                return (
                    "Source-bound Learn completion requires successful source.handoff, or "
                    'outcome "no_change" with explicit evidence citing ' + citation
                )
    if status == "completed" and (task.ref == "Tasks/repair" or any(
            item.get("tool") == "harness.repair" for item in context.get("trace", [])
            if isinstance(item, dict))):
        from obsidience.harness.execution.repair import PASS_ATTEMPT_LIMIT, repair_attempt_count

        snapshot = context.get("_harness_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("status") not in {"healthy", "degraded"}:
            return "Repair completion requires a current harness.status snapshot after the last recovery operation"
        if (repair_attempt_count(context) < PASS_ATTEMPT_LIMIT
                and any(row.get("operation") in {"retry", "settle"} for row in snapshot.get("repair_plan", []) if isinstance(row, dict))):
            return "Repair still has an eligible recovery operation; perform it or report the pass failed"
    error = _generated_runbook_completion_error(status, context)
    if error:
        return error
    if task.ref == 'Tasks/audit' and status != 'failed':
        case_id = (context.get('params') or {}).get('optimization_case')
        report = context.get('_harness_optimization')
        if not case_id or not isinstance(report, dict) or report.get('case_id') != case_id or not report.get('report_id'):
            return 'Audit completion requires the actual AutoSaddler report for its bound optimization case'
    error = _computer_completion_error(task, status, context, verification)
    if error:
        return error
    staged, approved, rejected = staged_proposal_states(context)
    if staged and status != "review":
        return 'an execution with staged proposals must finish with status "review"'
    if outcome and outcome not in {"changed", "no_change"}:
        return "outcome must be changed or no_change"
    if outcome == "no_change" and status != "completed":
        return 'outcome "no_change" requires status "completed"'
    if outcome == "no_change" and staged:
        return 'outcome "no_change" cannot accompany staged proposals'
    if outcome == "no_change" and approved:
        return 'outcome "no_change" cannot accompany an approved change'
    if outcome == "no_change" and rejected:
        return 'outcome "no_change" cannot accompany a reviewed proposal'
    if outcome == "no_change" and not evidence:
        return 'outcome "no_change" requires explicit evidence'
    if outcome == "no_change" and context.get("_link_proposal_rejection"):
        return (
            "the Link draft is still rejected: " + context["_link_proposal_rejection"]
            + "; correct the proposal or finish failed with this blocker. "
            "A rejected draft does not establish that the Articles are already linked"
        )

    evidence_bound = evidence_bound_completion(task.ref, context)
    if (
        status == "completed"
        and not staged
        and not approved
        and not rejected
        and evidence_bound
        and (
            outcome != "no_change" or not evidence
        )
    ):
        return (
            'this evidence-bound execution has no staged change. After completing the inspection, '
            'send {"status":"completed","outcome":"no_change","evidence":["what was inspected"],'
            '"summary":"why no change was warranted"}. outcome and evidence are separate args fields, '
            'not text inside summary. If an input is inaccessible or the inspection is incomplete, '
            'send {"status":"failed","summary":"the exact blocker"}; do not invent a change to finish'
        )
    if status != "review":
        return None
    staged_targets = {
        str(item.get("target", ""))
        for item in (staged or [])
        if isinstance(item, dict) and item.get("target")
    }
    from obsidience.harness.knowledge.review import list_proposals

    incomplete = [
        row
        for row in list_proposals()
        if (
            str(row.get("task", "")) == task.ref
            or str(row.get("target", "")) in staged_targets
        )
        and str(row.get("blocked_reason", "")).startswith(
            "Merge is incomplete; no redirect proposal exists for:"
        )
    ]
    if incomplete:
        detail = " | ".join(str(row["blocked_reason"]) for row in incomplete)
        return (
            "review cannot complete while an archive lacks redirect proposals. "
            + detail
            + ". Read every exact missing Article, stage its complete redirect update, "
            "then call task.complete again."
        )
    if staged:
        return None
    if task.meta.get("acceptance"):
        return None
    if approved:
        return (
            "The owner already approved this execution's proposal; no pending Review remains. "
            'Finish with {"status":"completed","outcome":"changed","summary":"the approved change"}. '
            'The controller supplies the approval evidence. Do not stage another proposal.'
        )
    if rejected:
        return (
            "The owner already rejected this execution's proposal; no pending Review remains. "
            'Finish with status failed and report that decision without claiming a change or resubmitting it.'
        )
    return (
        "review requires a proposal staged by this exact execution or an explicit "
        "acceptance gate authored on the Task; a deferred downstream activation "
        "completes the calling Task honestly"
    )

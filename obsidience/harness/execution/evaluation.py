"""Pure frozen trials and paired, per-case refinement acceptance.

The frozen-response experiment follows AutoSaddler's evaluation idea; it is
implemented locally with exact fixtures and protected holdout nonregression.
This module imports no Capability, model, ledger, or filesystem owner.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math


def _text(value, name: str, limit: int = 128, *, empty: bool = False) -> None:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f"{name} must be a bounded string")


def _integer(value, name: str, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")


def _object(value, required: set, optional: set, name: str) -> None:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise ValueError(f"{name} has missing or unknown fields")


def _json(value, *, limit: int = 64_000) -> str:
    def check(item, depth=0):
        if depth > 8:
            raise ValueError("JSON nesting exceeds the fixture bound")
        if item is None or type(item) in {str, bool, int}:
            return
        if type(item) is float and math.isfinite(item):
            return
        if isinstance(item, (dict, list)) and len(item) <= 128:
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError("JSON object keys must be strings")
                item = item.values()
            for child in item:
                check(child, depth + 1)
            return
        raise ValueError("Fixture contains an invalid JSON value")

    check(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(encoded) > limit:
        raise ValueError("JSON exceeds the fixture size bound")
    return encoded


def _strings(value, name: str, maximum: int, *, width: int = 128) -> None:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded list")
    for item in value:
        _text(item, name, width)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} contains duplicates")


def _validate_case(case: dict) -> None:
    _json(case)
    _object(case, {"id", "split", "objective", "max_steps", "responses", "expected"},
            {"bindings", "knowledge", "conversation"}, "case")
    _text(case["id"], "case id")
    if case["split"] not in ("train", "holdout"):
        raise ValueError("case split must be train or holdout")
    _text(case["objective"], "objective", 4000)
    _integer(case["max_steps"], "max_steps", 1, 8)
    if "bindings" in case and not isinstance(case["bindings"], dict):
        raise ValueError("bindings must be a JSON object")
    for field in ("knowledge", "conversation"):
        if field in case:
            _text(case[field], field, 12_000, empty=True)
    responses = case["responses"]
    if not isinstance(responses, list) or len(responses) > 32:
        raise ValueError("responses must contain at most 32 fixtures")
    keys, tools = set(), set()
    for response in responses:
        _object(response, {"tool", "args", "result"}, set(), "response")
        _text(response["tool"], "response tool")
        if response["tool"] == "task.complete" or not isinstance(response["args"], dict):
            raise ValueError("response must bind a non-completion Tool to an argument object")
        if not isinstance(response["result"], (str, dict)):
            raise ValueError("response result must be text or a JSON object")
        _json(response["result"], limit=16_000)
        key = (response["tool"], _json(response["args"], limit=16_000))
        if key in keys:
            raise ValueError("duplicate exact Tool/argument fixture")
        keys.add(key)
        tools.add(response["tool"])
    expected = case["expected"]
    _object(expected, {"status", "required_tools", "max_tool_calls"},
            {"outcome", "summary_contains"}, "expected")
    if expected["status"] not in ("completed", "failed", "review"):
        raise ValueError("expected status is invalid")
    _strings(expected["required_tools"], "required_tools", 7)
    _integer(expected["max_tool_calls"], "max_tool_calls", 0, 7)
    if len(expected["required_tools"]) > expected["max_tool_calls"] or not set(expected["required_tools"]) <= tools:
        raise ValueError("required Tools must have fixtures and fit the call budget")
    if "outcome" in expected:
        _text(expected["outcome"], "expected outcome")
    if "summary_contains" in expected:
        _strings(expected["summary_contains"], "summary_contains", 8, width=500)


def validate_suite(suite: dict) -> None:
    """Validate frozen input structure; accepted Tool authority is checked by its owner."""
    _object(suite, {"schemaVersion", "cases", "repetitions"}, set(), "suite")
    if type(suite["schemaVersion"]) is not int or suite["schemaVersion"] != 1:
        raise ValueError("suite schemaVersion must be 1")
    _integer(suite["repetitions"], "repetitions", 1, 3)
    cases = suite["cases"]
    if not isinstance(cases, list) or not 2 <= len(cases) <= 6:
        raise ValueError("suite must contain two to six cases")
    for case in cases:
        _validate_case(case)
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("case IDs must be distinct")
    if {case["split"] for case in cases} != {"train", "holdout"}:
        raise ValueError("suite requires train and holdout cases")


class FrozenTrial:
    """One bounded trial; every observation comes only from its frozen fixture."""

    def __init__(self, case: dict):
        _validate_case(case)
        self.case = deepcopy(case)
        self.max_steps = case["max_steps"]
        self.passed = False
        self.error: str | None = None
        self.tool_count = 0
        self.calls: list[dict] = []
        self._expected = deepcopy(case["expected"])
        self._responses = {
            (row["tool"], _json(row["args"])): row["result"] if isinstance(row["result"], str) else _json(row["result"])
            for row in deepcopy(case["responses"])
        }
        self._terminal: dict | None = None

    def _finish(self, status: str, summary: str, reason: str) -> dict:
        self._terminal = {"done": True, "status": status, "summary": summary,
                          "observation": _json({"passed": self.passed, "reason": reason})}
        return dict(self._terminal)

    async def handle(self, name: str, args: dict) -> dict:
        if self._terminal is not None:
            return dict(self._terminal)
        try:
            _text(name, "Tool name")
            if not isinstance(args, dict):
                raise ValueError("Tool arguments must be a JSON object")
            encoded = _json(args, limit=16_000)
        except ValueError as exc:
            self.error = "Invalid evaluation invocation: " + str(exc)
            return self._finish("failed", "Invalid evaluation invocation.", self.error)
        self.calls.append({"tool": name, "args": deepcopy(args)})
        if name == "task.complete":
            return self._complete(args)
        self.tool_count += 1
        key = (name, encoded)
        if key not in self._responses:
            self.error = "No frozen response matches the exact Tool and arguments."
            return self._finish("failed", "Evaluation stopped at a fixture gap.", self.error)
        if len(self.calls) >= self.max_steps:
            return self._finish("failed", "Evaluation exhausted its step budget.", "No completion within max_steps")
        return {"done": False, "observation": self._responses[key]}

    def _complete(self, args: dict) -> dict:
        status = args.get("status") if args.get("status") in ("completed", "failed", "review") else "failed"
        summary = args.get("summary") if isinstance(args.get("summary"), str) else "Invalid evaluation completion."
        reason = "Completion did not satisfy the fixed criteria."
        try:
            _object(args, {"status", "summary"}, {"outcome", "evidence", "verification"}, "completion")
            if args["status"] not in ("completed", "failed", "review"):
                raise ValueError("completion status is invalid")
            _text(args["summary"], "completion summary", 2000)
            if "outcome" in args:
                _text(args["outcome"], "completion outcome", empty=True)
            if "evidence" in args:
                _strings(args["evidence"], "completion evidence", 8, width=500)
            if "verification" in args:
                _object(args["verification"], {"status", "observation"}, set(), "verification")
                if args["verification"]["status"] not in ("established", "not_established"):
                    raise ValueError("verification status is invalid")
                _text(args["verification"]["observation"], "verification observation", 1000)
            expected = self._expected
            called = {call["tool"] for call in self.calls[:-1]}
            self.passed = (
                status == expected["status"] and set(expected["required_tools"]) <= called
                and self.tool_count <= expected["max_tool_calls"] and len(self.calls) <= self.max_steps
                and ("outcome" not in expected or args.get("outcome") == expected["outcome"])
                and all(text in summary for text in expected.get("summary_contains", []))
            )
            if self.passed:
                reason = "Completion satisfied the fixed criteria."
        except ValueError as exc:
            reason = str(exc)
        return self._finish(status, summary[:2000], reason)


def compare_observations(parent: list, child: list) -> dict:
    """Require paired full coverage and per-case success; timing cannot override failure."""
    result = {"verdict": "incomplete", "counts": {}, "fixed": [], "regressed": [], "unchanged": []}

    def validate(rows):
        if not isinstance(rows, list) or not 2 <= len(rows) <= 18:
            raise ValueError("observations must contain a bounded complete suite")
        keys, cases = [], {}
        for row in rows:
            if not isinstance(row, dict) or not {"case_id", "split", "repetition", "passed", "error"} <= row.keys():
                raise ValueError("observation is missing required fields")
            _json(row)
            _text(row["case_id"], "case_id")
            if row["split"] not in ("train", "holdout") or type(row["passed"]) is not bool or row["error"] is not None:
                raise ValueError("observation has an error or invalid result")
            _integer(row["repetition"], "repetition", 1, 3)
            if "status" in row and row["status"] not in ("completed", "failed", "review"):
                raise ValueError("observation status is invalid")
            if "summary" in row:
                _text(row["summary"], "observation summary", 2000, empty=True)
            if "tool_count" in row:
                _integer(row["tool_count"], "tool_count", 0, 8)
            if row.get("prompt_tokens") is not None:
                _integer(row["prompt_tokens"], "prompt_tokens", 0, 1_000_000)
            for metric in ("duration_ms", "elapsed_ms"):
                if metric in row and (type(row[metric]) not in {int, float} or not math.isfinite(row[metric]) or row[metric] < 0):
                    raise ValueError("observation duration is invalid")
            if "actions" in row:
                if not isinstance(row["actions"], list) or len(row["actions"]) > 8:
                    raise ValueError("observation actions exceed the step bound")
                for action in row["actions"]:
                    _object(action, {"tool", "args"}, set(), "observed action")
                    _text(action["tool"], "observed Tool")
                    if not isinstance(action["args"], dict):
                        raise ValueError("observed arguments must be a JSON object")
            key = (row["case_id"], row["split"], row["repetition"])
            if key in keys or row["case_id"] in cases and cases[row["case_id"]] != row["split"]:
                raise ValueError("duplicate or inconsistent case identity")
            keys.append(key)
            cases[row["case_id"]] = row["split"]
        if not 2 <= len(cases) <= 6 or set(cases.values()) != {"train", "holdout"}:
            raise ValueError("both suite splits must be represented")
        repetitions = max(key[2] for key in keys)
        if len(keys) != len(cases) * repetitions:
            raise ValueError("missing case repetitions")
        return keys

    try:
        keys = validate(parent)
        if validate(child) != keys:
            raise ValueError("ordered comparison coverage differs")
    except (ValueError, TypeError, OverflowError, RecursionError):
        return result
    for key, before, after in zip(keys, parent, child):
        group = "fixed" if not before["passed"] and after["passed"] else "regressed" if before["passed"] and not after["passed"] else "unchanged"
        result[group].append(dict(zip(("case_id", "split", "repetition"), key)))
    result["counts"] = {
        "total": len(keys), "train": sum(key[1] == "train" for key in keys),
        "holdout": sum(key[1] == "holdout" for key in keys),
        "parent_passed": sum(row["passed"] for row in parent),
        "child_passed": sum(row["passed"] for row in child),
        **{group: len(result[group]) for group in ("fixed", "regressed", "unchanged")},
    }
    result["verdict"] = (
        "regressed" if result["regressed"] else
        "passed" if all(row["passed"] for row in child) and any(row["split"] == "train" for row in result["fixed"]) else
        "not_improved"
    )
    return result

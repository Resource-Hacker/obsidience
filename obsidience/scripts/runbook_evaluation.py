"""Register fixed regression cases and activate the existing Generate Task.

Run from the project root with ``python -m obsidience.scripts.runbook_evaluation``.
Fixtures are developer-authored Source. Models cannot author grading criteria.
"""

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Freeze accepted dependencies and fixed cases")
    prepare.add_argument("fixture")
    prepare.add_argument("--origin-run", required=True)
    start = commands.add_parser("start", help="Queue Darwin's existing Generate Runbook Task")
    start.add_argument("case_id")
    args = parser.parse_args()
    from obsidience.harness.execution import refinement
    if args.command == "prepare":
        from pathlib import Path
        path = Path(args.fixture)
        if path.stat().st_size > 128_000:
            parser.error("fixture exceeds 128 KB")
        specification = json.loads(path.read_text())
        specification["origin_run_id"] = args.origin_run
        result = refinement.prepare_case(specification)
    else:
        from obsidience.harness.execution.scheduler import enqueue_named_event
        refinement.activation_context(args.case_id)
        result = enqueue_named_event("runbook.refine", {
            "refinement_case": args.case_id, "activation_key": "refine-" + args.case_id,
        }, expected_task=refinement.GENERATOR)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

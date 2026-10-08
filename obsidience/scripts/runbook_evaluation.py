"""Register fixed regression cases and activate the existing AutoSaddler Audit Task.

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
    start = commands.add_parser("start", help="Queue Heimdall AutoSaddler optimization")
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
        from obsidience.harness.execution import optimization
        prepared = optimization.adopt_runbook_case(refinement._current(args.case_id))
        result = optimization.queue(prepared['case_id'])
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

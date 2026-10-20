"""Instruction optimization of Agent and Runbook instructions (harness.optimize).

The one owner of the pinned AutoSaddler V2 and Harness2 engines; nothing outside
this package imports either. ADK trials are consumed through
``execution.adk.runner.run_adk_session``.

admission  incident admission, case preparation, the optimize run and publication
backend    the selected engine (OBSIDIENCE_OPTIMIZER_BACKEND) and its installed-source contract
scenario   AutoSaddler V2 scenario ports: trials, evaluator, acceptance, original search backend
harness2   Harness2 Propose-Probe-Compose refinement over the AutoSaddler artifact layer (default)
experience bounded training-only lessons from validated publications
incidents  receipt-bound decision captures and their contract evaluation
evaluation pure frozen trials and paired per-case acceptance
cases      frozen Runbook cases
store      the immutable evaluation-artifact store all of them share
"""

EXECUTIVE = 'Agents/Executive/Executive'
AUDITOR = 'Tasks/audit'
HEIMDALL = 'Agents/Heimdall/Heimdall'

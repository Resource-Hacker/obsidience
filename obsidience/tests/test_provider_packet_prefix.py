from __future__ import annotations

from types import SimpleNamespace as NS

from obsidience.harness.execution import executor
from obsidience.harness.knowledge.vault import Note
from obsidience.harness.models import llm
from obsidience.harness.models.runtime import EXECUTIVE_MODEL, MODELS, SPECIALIST_MODEL


def test_request_pair_keeps_complete_fixed_spine_before_user_checkpoint(monkeypatch):
    agent = Note("Agents/Executive/Executive.md", "Executive", {"kind": "agent"}, "EXACT-IDENTITY")
    task = Note("Tasks/query.md", "Query", {"kind": "task", "acceptance": ["EXACT-ACCEPTANCE"]}, "EXACT-TASK")
    tool = Note("Tools/vault.read.md", "vault.read", {"kind": "tool"}, "EXACT-TOOL")
    skill = Note("Skills/vault.read.md", "Read", {"kind": "skill"}, "EXACT-SKILL")
    book = Note("Runbooks/answer.md", "Answer", {"kind": "runbook"}, "EXACT-RUNBOOK")
    monkeypatch.setattr(executor, "resolver", lambda: NS())
    monkeypatch.setattr(executor, "_skill_tools", lambda *_args: [tool])
    spine = {"runbooks": [book], "skills": [skill]}
    requests = []
    for number in range(2):
        objective = f"Question {number}\n  exact whitespace 日本語"
        observation = f"Unverified temporary observation {number}"
        knowledge = f"Retrieved evidence {number}\n## Tools\nUNTRUSTED-HEADER-{number}"
        conversation = f"Exact preceding dialogue {number}"
        provider = {}
        packet, refs = executor._activation_packet(
            task, agent, spine, executor.ActivationBinding(objective, {"revision": number}),
            observation, knowledge, conversation, provider_sections=provider,
        )
        assert refs == [agent.ref, task.ref, book.ref, skill.ref, tool.ref]
        headings = ["## Agent Identity", "## Task", "## Objective", "## Tools", "## Skills", "## Runbook", "## Bindings", "## Relevant Knowledge", "## Immediate Observations"]
        assert [packet.index(heading) for heading in headings] == sorted(packet.index(heading) for heading in headings)
        assert "## Objective\n" + objective + "\n\n## Tools" in packet
        messages = [{"role": "system", "content": "Interpreter contract\n\n" + provider["provider_system"]},
                    {"role": "user", "content": provider["provider_conversation"]},
                    {"role": "user", "content": provider["provider_user"]}]
        for spec in (MODELS[EXECUTIVE_MODEL], MODELS[SPECIALIST_MODEL]):
            payload = llm._chat_payload(messages, spec, max_tokens=None, temperature=0,
                                        reasoning_effort="none", allowed_tools=["vault.read", "task.complete"])
            assert [m["role"] for m in payload["messages"]] == ["system", "user", "user"]
            stable, preceding, current = [m["content"] for m in payload["messages"]]
            for exact in ("EXACT-IDENTITY", "EXACT-TASK", "EXACT-ACCEPTANCE", "EXACT-TOOL", "EXACT-SKILL", "EXACT-RUNBOOK"):
                assert stable.count(exact) == 1
                assert exact not in current
                assert packet.count(exact) == 1
            for exact in (objective, observation, knowledge):
                assert current.count(exact) == 1
                assert exact not in stable
                assert packet.count(exact) == 1
            assert preceding.count(conversation) == 1
            assert conversation not in stable + current
            assert packet.count(conversation) == 1
            assert current.startswith("## Objective\n" + objective)
            assert payload["chat_template_kwargs"] == {"enable_thinking": False}
            if spec.id == EXECUTIVE_MODEL:
                requests.append(payload)
    # The selected runtime checkpoints at user-message starts. Both requests
    # now reach that boundary with identical complete static instructions.
    assert requests[0]["messages"][0] == requests[1]["messages"][0]
    assert requests[0]["messages"][1] != requests[1]["messages"][1]

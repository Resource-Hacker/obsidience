# First run

With the Vault initialized and `obsidience/obsidience.toml` in place, bring the
Harness up step by step and observe each result before adding the next layer.

## Check the Vault and index

```sh
./obsidience/scripts/obsidience status   # Article, Task and proposal counts; speech transport
./obsidience/scripts/obsidience index    # synchronize the retrieval index
./obsidience/scripts/obsidience search "golden ontology"
```

`index` needs the configured embedding service (`embed_url`). `search` runs the
same hybrid lexical + dense retrieval the Agents use and prints exact Article
refs.

## Start the Harness

```sh
./obsidience/scripts/obsidience serve
```

`serve` runs the API and the scheduler in one process. The API listens on
loopback port **8765** by default (`host`, `port`, or the `OBSIDIENCE_PORT`
environment variable) and admits only loopback same-origin requests. Startup
prewarms retrieval before the API accepts work.

In a desktop installation the Harness runs as the user service
`obsidience-harness-dev.service`, wanted by the Shell session target; the
native UI is started by the configured desktop session.

## The command-line interface

| Command | Purpose |
| --- | --- |
| `obsidience init [--vault-dir PATH]` | Create a local Vault from the reviewed starter graph |
| `obsidience serve` | Run the daemon (API + scheduler) |
| `obsidience status` | Vault and Harness status |
| `obsidience index` | Synchronize the search index |
| `obsidience search QUERY…` | Hybrid search over the accepted graph |
| `obsidience tasks` | List Task Articles |
| `obsidience run REF` | Run one Task now |
| `obsidience review [list\|approve\|reject] [NAME] [--reason TEXT]` | List or decide staged proposals |

All commands go through `./obsidience/scripts/obsidience`, which runs the
Harness with the project's `.venv`.

## Talk to the Executive

Typed Chat and final speech transcripts both enter the Executive Agent's one
Google ADK conversation. In the Shell, open the **Chat** pane; it also owns the
voice mode controls (Wake word, Realtime, Mute). The Executive answers in
ordinary text when its context suffices and uses its direct Skills (search,
reading Articles, web lookup, observing windows and so on) when it needs a
Tool. The Graph pane shows the Thinking Packet light up as it answers.

## Review what the Agents propose

Agents never write accepted Knowledge directly. They stage proposals, which
wait in **Reviews** (or `obsidience review list`) until you approve or reject
them. Approval is atomic, pinned to the Article's base revision, and commits to
the Vault's local audit repository. See [Knowledge](../articles/knowledge.md).

## Next steps

- Turn on the layers you need: [Memory](../memory.md),
  [Realtime voice](../modules/harness/voice.md), the
  [Code graph](../modules/shell/graph-ui.md#code-view).
- Read the [Ontology](../ontology/index.md) to understand why an Article link
  never grants a Tool.
- Restart only what you changed: backend changes need only a Harness reload,
  graph changes a UI rebuild and graph presenter reload, and documentation or
  instruction-only changes need no restart.

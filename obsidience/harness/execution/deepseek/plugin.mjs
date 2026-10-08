// Obsidience's application port. DeepSeek's agent-loop owns all model decisions.
// Transport is private inherited pipes. Upstream persistence owns conversations;
// image bytes and the current capability dispatch remain activation-local.
import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { LlmAdapter, LlmError, createUserMessage, createAssistantMessage, createSystemMessage, freezeMessage, attributionHeaders } from '@deepseek-ai/dsh-llm';
import { Session, interruptedTurnClosers } from '@deepseek-ai/dsh-session';
import { toolPairingBalancedBefore } from '@deepseek-ai/dsh-compaction';

export const inject = ['agents', 'llm', 'tools', 'systemPrompt', 'sessions', 'sessionPersistence', 'sessionProjections', 'obsidienceMemory', 'tokenMeter', 'compaction'];

export function apply(ctx) {
  const runs = new Map();
  const activations = new Set();
  const sessions = new Map();
  const pending = new Map();
  const models = new Map();
  const send = value => process.stdout.write(JSON.stringify(value) + '\n');
  function request(run, method, params, signal) {
    const id = randomUUID();
    let wake;
    const values = [];
    let ended = false;
    const receive = value => { values.push(value); wake?.(); wake = undefined; };
    pending.set(id, receive);
    const abort = () => { ended = true; receive({ error: 'Executive cancelled' }); };
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    else send({ run, id, method, params });
    return {
      async *[Symbol.asyncIterator]() {
        try {
          while (true) {
            if (!values.length) await new Promise(resolve => { wake = resolve; });
            const value = values.shift();
            if (value.error) throw value.code ? new LlmError(value.error, value.code) : new Error(value.error);
            if (ended || value.done) return;
            yield value.result;
          }
        } finally {
          pending.delete(id);
          signal?.removeEventListener('abort', abort);
        }
      },
    };
  }
  async function call(run, method, params, signal) {
    for await (const value of request(run, method, params, signal)) return value;
    throw new Error('Executive port closed before a result');
  }
  class ObsidienceModel extends LlmAdapter {
    async resolveModel(provider, model) {
      const spec = models.get(model);
      if (!spec) throw new Error('Unknown Obsidience model');
      return { provider, id: model, name: model,
        context: { contextWindow: spec.context_tokens },
        defaultMaxTokens: spec.max_output_tokens,
        reasoning: { efforts: ['none', 'low', 'medium', 'high', 'xhigh'].map(id => ({ id, name: id })) },
        inputModalities: spec.capabilities.includes('vision') ? ['text', 'image'] : ['text'] };
    }
    async *stream(options) {
      const { signal, ...wire } = options;
      const state = sessions.get(options.sessionId)?.active;
      if (!state) throw new Error('No admitted Executive turn owns this model request');
      yield* request(state.run, 'model', { ...wire, headers: attributionHeaders() }, signal);
    }
  }
  ctx.effect(() => ctx.llm.registerAdapter(['obsidience'], new ObsidienceModel()));
  const user = text => createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text }] });
  const ownerMessage = (id, text) => freezeMessage({ id, role: 'user',
    source: { kind: 'user' }, content: [{ type: 'text', text }] });
  const contextMessage = (text, form = 'context') => createUserMessage({
    source: { kind: `plugin:obsidience.${form}`, form: 'recall' }, content: [{ type: 'text', text }],
  });
  const formOf = event => event?.type === 'user/message' && event.data.source?.kind?.startsWith('plugin:obsidience.')
    ? event.data.source.kind.slice('plugin:obsidience.'.length) : undefined;
  // Host-only projection of the log state this port reads, maintained from
  // committed events (and folded on demand for restored sessions) instead of
  // dsh's deprecated synchronous eventAt/snapshotEvents reads: the latest 80
  // settlement records, the summary count, and the seqs of runtime context,
  // recalled memory and interrupted text replies not yet replaced.
  const NATIVE_STATE = 'obsidience.native';
  const without = (seqs, cited) => seqs.filter(seq => !cited.includes(seq));
  ctx.sessionProjections.register({
    key: NATIVE_STATE,
    stateVersion: 1,
    stateSchema: { parse(value) {
      if (!Array.isArray(value?.outcomes) || !Number.isSafeInteger(value.compactions)
          || !Array.isArray(value.context) || !Array.isArray(value.interrupted)) {
        throw new Error('Invalid Obsidience native session projection');
      }
      return value;
    } },
    init: () => ({ outcomes: [], compactions: 0, context: [], interrupted: [] }),
    apply(state, event) {
      const form = formOf(event);
      if (form === 'outcome' || form === 'command-outcome') {
        return { ...state, outcomes: [...state.outcomes, JSON.parse(event.data.content[0].text)].slice(-80) };
      }
      if (form === 'context' || form === 'memory') return { ...state, context: [...state.context, event.seq] };
      if (event.type === 'compaction/summary') return { ...state, compactions: state.compactions + 1 };
      if (event.type === 'assistant/message' && event.data.interrupted
          && !event.data.message.content.some(block => block.type === 'tool-call')) {
        return { ...state, interrupted: [...state.interrupted, event.seq] };
      }
      const cited = event.sourceEventSeqs ?? [];
      if (cited.some(seq => state.context.includes(seq) || state.interrupted.includes(seq))) {
        return { ...state, context: without(state.context, cited), interrupted: without(state.interrupted, cited) };
      }
      return state;
    },
  });
  const nativeState = session => ctx.sessionProjections.stateOf(session, NATIVE_STATE);
  // The host reads only the provider window: the system prompt and the exchanges
  // from the anchor owner message (live context kept for placement), so this
  // pipe stays bounded while the native log keeps everything.
  function windowOf(messages, anchor) {
    const start = anchor ? messages.findIndex(m => m.id === anchor && m.source?.kind === 'user') : -1;
    if (start <= 0) return messages;
    const live = m => m.role === 'system' || ['plugin:obsidience.context', 'plugin:obsidience.memory'].includes(m.source?.kind);
    return [...messages.slice(0, start).filter(live), ...messages.slice(start)];
  }
  function snapshot(session, anchor) {
    const state = nativeState(session);
    return { id: session.id, revision: session.seq, messages: windowOf(session.deriveMessages(), anchor),
      pressure: ctx.tokenMeter.measure(session),
      compaction_count: state.compactions,
      tools: session.requestHeader()?.tools ?? [],
      reasoning_effort: session.requestHeader()?.config.reasoningEffort ?? 'none',
      outcomes: [...state.outcomes] };
  }
  function seedHistory(config) {
    if (!config.bootstrap?.length) return [];
    const seed = Session.create(config.session_id);
    // The logged events are the seed; collect each one as it is appended.
    const events = [];
    const append = (...args) => events.push(seed.append(...args));
    append('turn/start', { turn: 1 });
    append('step/start', { turn: 1, step: 1 });
    append('system/message', { turn: 1, step: 1,
      message: createSystemMessage(config.system) }, { surfaceOp: 'append' });
    append('step/end', { turn: 1, step: 1 });
    append('turn/end', { turn: 1, reason: { kind: 'completed' } });
    let turn = 1, open = false;
    const close = completed => {
      if (!open) return;
      append('step/end', { turn, step: 1 });
      append('turn/end', { turn, reason: { kind: completed ? 'completed' : 'interrupted' } });
      open = false;
    };
    for (const row of config.bootstrap || []) {
      if (row.role === 'user') {
        close(false); turn++; open = true;
        append('turn/start', { turn });
        append('step/start', { turn, step: 1 });
        append('user/message', ownerMessage(row.id, row.text), { surfaceOp: 'append' });
      } else if (row.role === 'assistant' && open) {
        append('assistant/message', { turn, step: 1,
          message: createAssistantMessage({ source: { provider: 'obsidience', model: config.model.id },
            content: [{ type: 'text', text: row.text }] }), stream: [] },
        { surfaceOp: 'append' });
        close(true);
      }
    }
    close(false);
    return events;
  }
  function supersedeContext(session) {
    const current = new Set(nativeState(session).context);
    for (const seq of [...session.surface.nodes]) {
      if (!current.has(seq)) continue;
      session.append('user/message', contextMessage('[Earlier request context superseded.]', 'expired-context'),
        { surfaceOp: { op: 'replace', startSeq: seq, endSeq: seq }, sourceEventSeqs: [seq] });
    }
  }
  function excludeInterruptedReplies(session) {
    const interrupted = new Set(nativeState(session).interrupted);
    for (const seq of [...session.surface.nodes]) {
      if (!interrupted.has(seq)) continue;
      session.append('user/message', contextMessage(
        '[The preceding reply was interrupted. Its partial text is not an accepted answer.]', 'interrupted'),
      { surfaceOp: { op: 'replace', startSeq: seq, endSeq: seq }, sourceEventSeqs: [seq] });
    }
  }
  // Idle maintenance at an upstream step boundary, inside the open turn that a
  // tool/result replacement requires. The mounted upstream pruner trims large
  // Tool results; a summary of the older span follows only while pressure stays
  // at or above the limit, through compaction-basic's own region transaction,
  // keeping its recent tail (retainRatio of W - O) verbatim.
  async function maintainContext(agent, config, signal) {
    signal.throwIfAborted();
    const limit = config.maintain.threshold * config.model.context_tokens;
    const measure = () => ctx.tokenMeter.measure(agent.session);
    const pruner = ctx.get('toolResultPruner');
    const pruned = pruner && measure().totalTokens >= limit ? pruner.pruneSession(agent.session).pruned.length : 0;
    const { totalTokens, nodes } = measure();
    if (totalTokens < limit) return { pruned, compacted: false };
    const retain = (config.model.context_tokens - config.model.max_output_tokens) * ctx.compaction.config.retainRatio;
    // Node 0 is the system prompt and is never summarized.
    let keep = nodes.length, kept = 0;
    while (keep > 1 && kept < retain) kept += nodes[--keep].tokens;
    while (keep > 1 && !toolPairingBalancedBefore(agent.session, nodes[keep].seq)) keep--;
    if (keep <= 1) return { pruned, compacted: false };
    await ctx.compaction.compactRegion(nodes[1].seq, nodes[keep - 1].seq, agent, signal);
    return { pruned, compacted: true };
  }
  async function inspectStored(id, anchor) {
    const live = sessions.get(id);
    if (live) {
      return snapshot(live.handle.agent.session, anchor);
    }
    if (!await ctx.sessionPersistence.stat(id)) return null;
    const reader = await ctx.sessionPersistence.open(id, 'read');
    try {
      const { events, eventState } = await reader.read();
      const closers = interruptedTurnClosers(events);
      const session = !closers.length && !reader.header.isSeeded
        ? Session.fromRestore(id, events, reader.header, reader.inheritedEventCount, eventState, ctx.sessions.messageProjections)
        : Session.create(id, [...events, ...closers], reader.header, reader.inheritedEventCount, ctx.sessions.messageProjections);
      excludeInterruptedReplies(session);
      return snapshot(session, anchor);
    } finally { await reader.close(); }
  }
  async function start(config) {
    const run = config.run;
    if (runs.has(run)) throw new Error('Executive activation already exists');
    const id = config.session_id || run;
    const state = { run, handle: undefined, cancelled: false, error: undefined, compact: config.compact,
      maintain: config.maintain, maintenance: new AbortController() };
    runs.set(run, state);
    models.set(config.model.id, config.model);
    try {
      let entry = sessions.get(id);
      if (entry?.active) throw new Error('This Executive conversation already has an active turn');
      const signature = JSON.stringify([config.model, config.effort, config.tools]);
      if (entry && entry.signature !== signature) {
        await entry.handle.dispose(); sessions.delete(id); entry = undefined;
      }
      if (entry) { entry.config = config; entry.active = state; }
      else {
        entry = { config, signature, active: state, handle: undefined };
        sessions.set(id, entry);
        const options = {
        agentOptions: { provider: 'obsidience', model: config.model.id,
          reasoningEffort: config.effort, maxTokens: config.model.max_output_tokens },
        setup(scope, agent) {
          let recalled;
          ctx.obsidienceMemory.attach(scope, async (ownerId, query, signal) => {
            if (!entry.active || entry.active.command || recalled === ownerId) return null;
            recalled = ownerId;
            return await call(entry.active.run, 'memory.recall', { query }, signal);
          });
          scope.effect(() => scope.systemPrompt.variable('obsidience_identity', () => entry.config.system));
          scope.effect(() => scope.systemPrompt.section({ name: 'obsidience', order: 0,
            text: '{{obsidience_identity}}', complete: true }));
          for (const tool of config.tools) {
            scope.effect(() => scope.tools.register({ ...tool,
              output: { schema: { type: 'string' }, render: (_args, value) => JSON.parse(value) },
              async execute(args, exec) {
                if (!entry.active) throw new Error('No admitted turn owns this Tool call');
                if (entry.active.compact || entry.active.maintain) throw new Error('Compaction cannot dispatch Tools');
                await ctx.sessions.flush(agent.session);
                return JSON.stringify(await call(entry.active.run, 'tool', { name: tool.name, args }, exec.signal));
              },
            }));
          }
          scope.on('agent/pre-step', async ({ signal, step }, next) => {
            if (!entry.active) return { kind: 'reject' };
            if (entry.active.maintain) {
              // Idle maintenance owns this turn: it works at the first step
              // boundary, then closes the turn without a step or model reply.
              entry.active.maintained = await maintainContext(agent, entry.config, signal);
              return { kind: 'reject' };
            }
            const boundary = await call(entry.active.run, 'boundary', { step }, signal);
            if (boundary.done) return { kind: 'reject' };
            const decision = await next();
            if (decision.kind === 'enter' && boundary.context) {
              return { ...decision, messages: [...decision.messages, contextMessage(boundary.context, 'steering')] };
            }
            return decision;
          });
          scope.on('agent/request-error', async ({ error }, next) => {
            const recovery = await next();
            if (recovery?.kind !== 'retry' && entry.active) entry.active.error = String(error?.message || error);
            return recovery;
          });
          scope.on('agent/error', ({ error }) => { if (entry.active) entry.active.error = String(error?.message || error); });
          scope.on('agent/turn-stopping', async () => {
            if (!entry.active || !entry.config.session_id) return;
            const outcome = await call(entry.active.run, 'settlement', {});
            agent.session.append('user/message', contextMessage(JSON.stringify({
              ...outcome, run_id: entry.active.run, reply_to: entry.config.turn_id,
            }), 'outcome'), { surfaceOp: 'append' });
          });
          scope.on('tools/result', (exec, result) => {
            if (result.isError && entry.active) send({ run: entry.active.run, method: 'tool_error', params: {
              name: exec.name, code: result.error.info?.code || 'TOOL_ERROR',
            } });
          });
        },
        };
        entry.handle = await (await ctx.sessionPersistence.stat(id)
          ? ctx.agents.resume({ ...options, resumeSessionId: id })
          : ctx.agents.create({ ...options, sessionId: id, meta: { cwd: config.cwd }, seed: seedHistory(config) }));
        // A crashed process must never release a previously queued command.
        entry.handle.agent.inbox.clear();
      }
      const handle = entry.handle;
      state.handle = handle;
      if (state.cancelled) handle.agent.cancel({ kind: 'user' });
      else if (config.command) {
        if (!config.session_id || config.continuation || !['lights.set', 'media.pause', 'task.complete'].includes(config.command.name)) {
          throw new Error('Explicit command requires its exact Executive owner turn');
        }
        state.command = config.command;
        await handle.agent.runMaintenance(async signal => {
          signal.throwIfAborted();
          excludeInterruptedReplies(handle.agent.session);
          supersedeContext(handle.agent.session);
          // This is a real owner request and controller-owned execution, not
          // model output or a fabricated model Tool-call span.
          handle.agent.session.append('user/message', ownerMessage(config.turn_id, config.objective),
            { surfaceOp: 'append' });
          handle.agent.session.append('user/message', contextMessage(JSON.stringify({
            status: 'started', command: config.command, run_id: run, reply_to: config.turn_id,
            instruction: 'Controller command admitted. A missing outcome means unknown delivery; never replay it.',
          }), 'command'), { surfaceOp: 'append' });
          state.commandAdmitted = true;
          await ctx.sessions.flush(handle.agent.session);
          signal.throwIfAborted();
          const result = await ctx.agents.withInitiator(handle.agent, () => handle.agent.ctx.tools.execute({
            callId: `command-${config.turn_id}`, name: config.command.name,
            arguments: config.command.args, agent: handle.agent, signal,
          }));
          state.commandResult = result.content;
          signal.throwIfAborted();
          const outcome = await call(run, 'command_complete', { isError: result.isError }, signal);
          signal.throwIfAborted();
          handle.agent.session.append('user/message', contextMessage(JSON.stringify({
            ...outcome, command: config.command, result: result.content,
            run_id: run, reply_to: config.turn_id,
          }), 'command-outcome'), { surfaceOp: 'append' });
          await ctx.sessions.flush(handle.agent.session);
        });
      } else if (config.compact) {
        state.compaction = await ctx.compaction.compactNow(handle.agent, state.maintenance.signal);
      } else if (config.maintain) {
        // Upstream opens one turn for this wake; maintainContext runs at its
        // first step boundary. Below the limit nothing is appended.
        const limit = config.maintain.threshold * config.model.context_tokens;
        if (ctx.tokenMeter.measure(handle.agent.session).totalTokens >= limit) {
          handle.agent.followup(contextMessage('[Idle context maintenance; not an owner request.]', 'maintenance'));
          await handle.agent.whenIdle();
        }
      } else {
        if (config.session_id) {
          excludeInterruptedReplies(handle.agent.session);
          supersedeContext(handle.agent.session);
          // The compiler supplies one runtime-context message; it supersedes
          // together with any recalled memory at the next owner turn.
          for (const message of config.messages) handle.agent.inject(contextMessage(message.content));
          handle.agent.followup(config.continuation
            ? contextMessage(config.objective, 'continuation') : ownerMessage(config.turn_id, config.objective));
        } else {
          for (const message of config.messages.slice(0, -1)) handle.agent.inject(user(message.content));
          handle.agent.followup(user(config.messages.at(-1).content));
        }
        await handle.agent.whenIdle();
      }
    } catch (error) {
      state.error = String(error?.message || error);
      if (state.commandAdmitted && state.handle) {
        state.handle.agent.session.append('user/message', contextMessage(JSON.stringify({
          status: state.cancelled ? 'interrupted' : 'failed', summary: '',
          command: state.command, result: state.commandResult,
          run_id: run, reply_to: config.turn_id, must_not_replay: true,
          instruction: 'Controller command did not settle. Use its existing receipt; do not infer or replay delivery.',
        }), 'command-outcome'), { surfaceOp: 'append' });
      }
    } finally {
      const entry = sessions.get(id);
      let session;
      if (entry?.active === state) {
        try {
          if (state.handle) {
            excludeInterruptedReplies(state.handle.agent.session);
            await ctx.sessions.flush(state.handle.agent.session);
            session = snapshot(state.handle.agent.session, config.window_anchor);
          }
        } catch (error) { state.error = String(error?.message || error); }
        entry.active = undefined;
        if (!config.session_id || !entry.handle) { await entry.handle?.dispose(); sessions.delete(id); }
      }
      runs.delete(run);
      send({ run, method: 'end', error: state.error, cancelled: state.cancelled,
        compacted: Boolean(state.compaction || state.maintained?.compacted), pruned: state.maintained?.pruned ?? 0, session });
    }
  }
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  input.on('line', line => {
    try {
      const value = JSON.parse(line);
      if (value.control) {
        const execute = async () => {
          const { session_id: id } = value.params;
          if (value.method === 'inspect') return inspectStored(id, value.params.window_anchor);
          if (value.method === 'close') {
            const entry = sessions.get(id);
            if (entry?.active) throw new Error('Cannot close an active Executive session');
            await entry?.handle.dispose(); sessions.delete(id); return { closed: id };
          }
          throw new Error('Unknown native session operation');
        };
        void execute().then(result => send({ control: value.control, result }),
          error => send({ control: value.control, error: String(error?.message || error) }));
      } else if (value.method === 'start') {
        const activation = start(value.params);
        activations.add(activation);
        void activation.finally(() => activations.delete(activation));
      }
      else if (value.method === 'cancel') {
        const state = runs.get(value.run);
        if (state) {
          state.cancelled = true;
          state.maintenance.abort();
          state.handle?.agent.cancel({ kind: 'user' });
        }
      } else if (value.method === 'context') {
        runs.get(value.run)?.handle?.agent.steer(contextMessage(value.text, 'steering'));
      } else if (value.id) pending.get(value.id)?.(value);
    } catch {
      // A broken private protocol is terminal; never interpret text as a Tool.
      process.exitCode = 1;
      input.close();
    }
  });
  input.on('close', async () => {
    for (const state of runs.values()) {
      state.cancelled = true;
      state.maintenance.abort();
      state.handle?.agent.cancel({ kind: 'parent' });
    }
    // Drain our settlement/flush as well as upstream maintenance before closing
    // the session's persistence handle.
    await Promise.allSettled([...activations]);
    await Promise.all([...sessions.values()].map(entry => entry.handle?.dispose()));
    process.exit(process.exitCode || 0);
  });
  send({ method: 'ready' });
}

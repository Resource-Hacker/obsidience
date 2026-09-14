// Obsidience's application port. DeepSeek's agent-loop owns all model decisions.
// Transport is private inherited pipes; sessions and images are memory-only.
import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { LlmAdapter, createUserMessage, attributionHeaders } from '@deepseek-ai/dsh-llm';

export const inject = ['agents', 'llm', 'tools', 'systemPrompt'];

export function apply(ctx) {
  const runs = new Map();
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
            if (value.error) throw new Error(value.error);
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
      yield* request(options.sessionId, 'model', { ...wire, headers: attributionHeaders() }, signal);
    }
  }
  ctx.effect(() => ctx.llm.registerAdapter(['obsidience'], new ObsidienceModel()));
  const user = text => createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text }] });
  async function start(config) {
    const run = config.run;
    if (runs.has(run)) throw new Error('Executive activation already exists');
    const state = { handle: undefined, cancelled: false, error: undefined };
    runs.set(run, state);
    models.set(config.model.id, config.model);
    try {
      const handle = await ctx.agents.create({
        sessionId: run,
        meta: { cwd: config.cwd },
        agentOptions: { provider: 'obsidience', model: config.model.id,
          reasoningEffort: config.effort, maxTokens: config.model.max_output_tokens },
        setup(scope, agent) {
          scope.effect(() => scope.systemPrompt.variable('obsidience_identity', () => config.system));
          scope.effect(() => scope.systemPrompt.section({ name: 'obsidience', order: 0,
            text: '{{obsidience_identity}}', complete: true }));
          for (const tool of config.tools) {
            scope.effect(() => scope.tools.register({ ...tool,
              output: { schema: { type: 'string' }, render: (_args, value) => JSON.parse(value) },
              async execute(args, exec) {
                return JSON.stringify(await call(run, 'tool', { name: tool.name, args }, exec.signal));
              },
            }));
          }
          scope.on('agent/pre-step', async ({ signal, step }, next) => {
            const boundary = await call(run, 'boundary', { step }, signal);
            if (boundary.done) return { kind: 'reject' };
            const decision = await next();
            if (decision.kind === 'enter' && boundary.context) {
              return { ...decision, messages: [...decision.messages, user(boundary.context)] };
            }
            return decision;
          });
          scope.on('agent/request-error', async ({ error }) => { state.error = String(error?.message || error); });
          scope.on('agent/error', ({ error }) => { state.error = String(error?.message || error); });
          scope.on('tools/result', (exec, result) => {
            if (result.isError) send({ run, method: 'tool_error', params: {
              name: exec.name, code: result.error.info?.code || 'TOOL_ERROR',
            } });
          });
        },
      });
      state.handle = handle;
      if (state.cancelled) handle.agent.cancel({ kind: 'user' });
      else {
        for (const message of config.messages.slice(0, -1)) handle.agent.inject(user(message.content));
        handle.agent.followup(user(config.messages.at(-1).content));
        await handle.agent.whenIdle();
      }
    } catch (error) {
      state.error = String(error?.message || error);
    } finally {
      await state.handle?.dispose();
      runs.delete(run);
      send({ run, method: 'end', error: state.error, cancelled: state.cancelled });
    }
  }
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  input.on('line', line => {
    try {
      const value = JSON.parse(line);
      if (value.method === 'start') void start(value.params);
      else if (value.method === 'cancel') {
        const state = runs.get(value.run);
        if (state) { state.cancelled = true; state.handle?.agent.cancel({ kind: 'user' }); }
      } else if (value.method === 'context') {
        runs.get(value.run)?.handle?.agent.steer(user(value.text));
      } else if (value.id) pending.get(value.id)?.(value);
    } catch {
      // A broken private protocol is terminal; never interpret text as a Tool.
      process.exitCode = 1;
      input.close();
    }
  });
  input.on('close', async () => {
    await Promise.all([...runs.values()].map(async state => {
      state.cancelled = true;
      state.handle?.agent.cancel({ kind: 'parent' });
      await state.handle?.dispose();
    }));
    process.exit(process.exitCode || 0);
  });
  send({ method: 'ready' });
}

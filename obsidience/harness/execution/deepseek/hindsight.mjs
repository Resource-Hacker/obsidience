// Native Cordis memory service. Obsidience's port owns bank scope and receipts;
// Hindsight owns retrieval. No second agent loop, wiki, or direct Tool registry.
import { Service } from '@deepseek-ai/cordis';
import { createUserMessage } from '@deepseek-ai/dsh-llm';

export default class Hindsight extends Service {
  constructor(ctx) { super(ctx, 'obsidienceMemory'); }

  attach(scope, recall) {
    scope.on('agent/pre-step', async ({ signal }, next) => {
      const decision = await next();
      if (decision.kind !== 'enter' || signal.aborted) return decision;
      const owner = decision.messages.filter(m => m.source?.kind === 'user').at(-1);
      if (!owner) return decision;
      const query = owner.content.filter(b => b.type === 'text').map(b => b.text).join('\n');
      const result = await recall(owner.id, query, signal);
      if (!result?.memories?.length) return decision;
      return { ...decision, messages: [...decision.messages, createUserMessage({
        source: { kind: 'plugin:obsidience.memory', form: 'recall' },
        content: [{ type: 'text', text: JSON.stringify(result) }],
      })] };
    });
  }
}

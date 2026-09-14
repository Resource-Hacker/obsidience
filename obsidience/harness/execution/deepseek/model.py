"""DeepSeek message/stream vocabulary over Obsidience's existing model owner."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from httpx_sse import aconnect_sse

from ...models import llm
from ...models.context import TaskContext, PROMPT_SAFETY_TOKENS


def wire_messages(messages: list[dict], images: dict) -> list[dict]:
    result = []
    def content(blocks):
        parts = []
        for block in blocks:
            if block['type'] == 'text':
                parts.append({'type': 'text', 'text': block['text']})
            elif block['type'] == 'image':
                image = images.get(block['attachment']['attachmentId'])
                parts.append({'type': 'image_url', 'image_url': {'url': image}}
                             if image else {'type': 'text', 'text': '[Earlier image consumed; observe again for current pixels.]'})
        if all(part['type'] == 'text' for part in parts):
            return '\n'.join(part['text'] for part in parts)
        return parts
    for message in messages:
        blocks = message['content']
        tool_results = [b for b in blocks if b['type'] == 'tool-result']
        if tool_results:
            for block in tool_results:
                value = content(block['content'])
                result.append({'role': 'tool', 'tool_call_id': block['toolCallId'],
                               'content': value if isinstance(value, str) else '\n'.join(
                                   part['text'] for part in value if part['type'] == 'text')})
                if isinstance(value, list):
                    result.append({'role': 'user', 'content': [
                        {'type': 'text', 'text': 'Current image returned by the preceding observation Tool:'},
                        *(part for part in value if part['type'] == 'image_url')]})
        else:
            row = {'role': message['role'], 'content': content(blocks)}
            calls = [b for b in blocks if b['type'] == 'tool-call']
            if calls:
                row['tool_calls'] = [{'id': b['id'], 'type': 'function',
                                     'function': {'name': b['name'], 'arguments': b['arguments']}}
                                    for b in calls]
            result.append(row)
    return result


def request_payload(messages, spec, effort, tools):
    """One native provider representation for execution and disposable prefill."""
    payload = llm._chat_payload(messages, spec, max_tokens=spec.max_output_tokens,
                                temperature=None, reasoning_effort=effort)
    payload.pop('response_format', None)
    payload['tools'] = [{'type': 'function', 'function': tool} for tool in tools]
    payload['parallel_tool_calls'] = False
    return payload


async def stream(options: dict, spec, effort: str, images: dict, send, metrics: dict):
    messages = wire_messages(options['messages'], images)
    payload = request_payload(messages, spec, effort, options.get('tools', []))
    projection = TaskContext()
    names = {call['id']: call['function']['name'] for row in messages for call in row.get('tool_calls', [])}
    for index, row in enumerate(messages):
        if row['role'] != 'tool' or not isinstance(row['content'], str):
            continue
        name = names.get(row['tool_call_id'], '')
        text = row['content'].removeprefix('Observation:\n')
        projection.remember_source_page(index, name, text, '', source_read_allowed=True)
        projection.remember_article_page(index, name, text, '', vault_read_allowed=True)
    async with llm.provider_client() as client:
        started = time.monotonic()
        capacity = spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS
        count = await projection.fit_payload(payload, spec, client, capacity)
        metrics.update(preflight_ms=round((time.monotonic()-started)*1000, 3), prompt_tokens=count.tokens)
        blocks = {}
        calls = {}
        finish = ''
        done = False
        loop = asyncio.get_running_loop()
        async with asyncio.timeout(llm.CHAT_TIMEOUT_SECONDS) as deadline:
            dispatched = time.monotonic()
            async with aconnect_sse(client, 'POST', f'{spec.base_url}/chat/completions',
                                    json=payload, headers=options['headers']) as events:
                events.response.raise_for_status()
                async for event in events.aiter_sse():
                    if event.data == '[DONE]':
                        done = True
                        break
                    data = json.loads(event.data)
                    if 'error' in data:
                        raise ValueError('Native provider rejected the request')
                    if usage := data.get('usage'):
                        cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
                        metrics['cached_input_tokens'] = cached
                        await send({'type': 'usage', 'usage': {
                            'inputTokens': max(0, usage.get('prompt_tokens', 0)-cached),
                            'outputTokens': usage.get('completion_tokens', 0),
                            'totalTokens': usage.get('total_tokens', 0), 'cacheReadTokens': cached}})
                    for choice in data.get('choices', []):
                        if choice.get('index', 0) != 0:
                            raise ValueError('Unexpected native provider choice')
                        delta = choice.get('delta') or {}
                        text = delta.get('content')
                        progress = bool(text or delta.get('tool_calls') or delta.get('reasoning_content') or delta.get('reasoning'))
                        # Private reasoning renews the deadline, but crosses neither the port nor durable history.
                        if progress:
                            deadline.reschedule(loop.time() + llm.CHAT_TIMEOUT_SECONDS)
                        if text:
                            if finish: raise ValueError('Native content after finish')
                            if 'text' not in blocks:
                                blocks['text'] = {'index': len(blocks), 'text': ''}
                                await send({'type': 'block-start', 'index': blocks['text']['index'], 'blockType': 'text'})
                            block = blocks['text']
                            block['text'] += text
                            await send({'type': 'text-delta', 'index': block['index'], 'text': text})
                        for call in delta.get('tool_calls', []):
                            key = call['index']
                            if key not in calls:
                                block = {'index': len(blocks), 'id': call.get('id') or str(uuid.uuid4()), 'name': '', 'arguments': ''}
                                calls[key] = block
                                blocks[f'call:{key}'] = block
                                await send({'type': 'block-start', 'index': block['index'], 'blockType': 'tool-call'})
                            block = calls[key]
                            function = call.get('function') or {}
                            block['name'] += function.get('name', '')
                            args = function.get('arguments', '')
                            block['arguments'] += args
                            await send({'type': 'tool-call-delta', 'index': block['index'], 'id': block['id'],
                                        **({'name': block['name']} if function.get('name') else {}), 'argumentsDelta': args})
                        if (text or delta.get('tool_calls')) and 'first_public_delta_ms' not in metrics:
                            metrics['first_public_delta_ms'] = round((time.monotonic()-dispatched)*1000, 3)
                        if choice.get('finish_reason'):
                            finish = choice['finish_reason']
        if not done or not finish:
            raise ValueError('Native stream disconnected before completion; no partial Tool is dispatched')
        for key, block in blocks.items():
            value = {'type': 'text', 'text': block['text']} if key == 'text' else {
                'type': 'tool-call', 'id': block['id'], 'name': block['name'], 'arguments': block['arguments']}
            await send({'type': 'block-end', 'index': block['index'], 'block': value})
        reason = {'stop': 'stop', 'tool_calls': 'tool-calls', 'length': 'max-tokens'}.get(finish, 'error')
        await send({'type': 'finish', 'reason': reason})
        metrics['generation_ms'] = round((time.monotonic()-dispatched)*1000, 3)
        return (blocks.get('text') or {}).get('text', ''), bool(calls), reason, projection.last_projection

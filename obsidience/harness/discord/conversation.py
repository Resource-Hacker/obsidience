"""Named-Agent Discord conversations on the Harness's existing native ADK loop.

The gateway supplies observed identities; this service never treats Discord
members as the workstation owner or writes to Executive Chat or Memory.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from .store import AGENT_REF, DiscordStore, snowflake


class DiscordConversations:
    def __init__(self, path: Path | None = None):
        if path is None:
            from ..config import CONFIG
            path = CONFIG.runtime_dir / 'discord-conversations.sqlite3'
        self.store = DiscordStore(path)
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: dict[str, asyncio.Task] = {}
        self._bindings = {}
        self._started = False
        self._closing = False

    async def start(self):
        if self._started:
            return
        from ..execution.adk import sessions
        self.store.start()
        try:
            # Attach outcome-unknown responses to any incomplete native calls;
            # these reads and journal writes dispatch no Tool or model work.
            for turn in self.store.recovery():
                token = sessions.CONVERSATION_BINDING.set(turn)
                try:
                    await sessions.close_interrupted_calls(turn.conversation_id, 'discord-recovery')
                finally:
                    sessions.CONVERSATION_BINDING.reset(token)
            for row in self.store.completed():
                self._memory(self.store.binding(row), row)
        except BaseException:
            self.store.close()
            raise
        self._closing = False
        self._started = True

    async def close(self):
        self._closing = True
        pending = list(self._pending.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.store.close()
        self._started = False
        self._locks.clear()

    def status(self):
        return {'started': self._started and not self._closing, 'agent_ref': AGENT_REF,
                'active_turns': len(self._pending)}

    async def submit(self, text: str, *, guild_id: str, channel_id: str, member_id: str,
                     request_id: str, source: str = 'text', memory_writeback: bool = True,
                     display_name: str = '') -> dict:
        if not self._started or self._closing:
            raise RuntimeError('Discord conversations are not running')
        try:
            turn, duplicate = self.store.admit(text, guild_id=guild_id, channel_id=channel_id,
                member_id=member_id, request_id=request_id, source=source,
                memory_writeback=memory_writeback, display_name=display_name)
        except ValueError:
            raise
        except Exception:
            raise RuntimeError('Discord request admission is unavailable') from None
        task = self._pending.get(turn.turn_id)
        if task is None and duplicate:
            return {**self.store.result(turn), 'duplicate': True}
        if task is None:
            if len(self._pending) >= 64:
                self.store.finish(turn, {'status': 'failed', 'reply': '', 'delivery': 'not_dispatched',
                                        'summary': 'Discord conversation ingress is at capacity'})
                return {**self.store.result(turn), 'duplicate': False}
            lock = self._locks.setdefault(turn.conversation_id, asyncio.Lock())
            task = asyncio.create_task(self._execute(turn, lock), name='obsidience-discord-' + turn.turn_id)
            self._pending[turn.turn_id] = task
            self._bindings[turn.turn_id] = turn
            task.add_done_callback(lambda value, identifier=turn.turn_id: self._settled(identifier))
        # Transport cancellation must not silently cancel or replay an admitted
        # member request. Explicit cancel/close owns that lifecycle.
        return {**await asyncio.shield(task), 'duplicate': duplicate}

    def _settled(self, identifier):
        task = self._pending.pop(identifier, None)
        turn = self._bindings.pop(identifier, None)
        if task is not None and task.cancelled() and turn is not None and self.store.db is not None:
            # Cancellation can arrive before the coroutine starts and reaches
            # its own finalizer. Its admitted ingress must still settle once.
            self.store.finish(turn, {'status': 'interrupted', 'reply': '', 'must_not_replay': True,
                                    'conversation_id': turn.conversation_id, 'turn_id': turn.turn_id})
        elif task is not None and not task.cancelled():
            task.exception()  # Observe an error even if its gateway went away.
        if turn is not None and not any(value.conversation_id == turn.conversation_id
                                        for value in self._bindings.values()):
            self._locks.pop(turn.conversation_id, None)

    async def cancel(self, *, guild_id: str, channel_id: str, member_id: str,
                     request_id: str | None = None):
        for value in (guild_id, channel_id, member_id):
            snowflake(value)
        if request_id is not None and (not isinstance(request_id, str) or not request_id
                or len(request_id) > 128 or any(ord(char) < 32 for char in request_id)):
            raise ValueError('Discord cancellation requires a bounded exact request id')
        tasks = []
        for identifier, turn in tuple(self._bindings.items()):
            if (request_id is None or turn.metadata['request_id'] == request_id) and all(
                    turn.metadata[key] == value for key, value in (
                    ('guild_id', guild_id), ('channel_id', channel_id), ('member_id', member_id))):
                if (task := self._pending.get(identifier)) is not None:
                    task.cancel()
                    tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _memory(self, turn, row):
        from ..memory.hindsight import MEMORY
        if not row['memory_writeback']:
            MEMORY.withhold(AGENT_REF, source='discord:' + turn.conversation_id, identifier=turn.turn_id)
            return
        result = self.store.result(turn)
        if row['state'] == 'completed' and result.get('reply'):
            # The speaker identity is observed Discord metadata, never a name
            # guessed from audio or an instruction supplied by another member.
            attribution = 'Discord member ' + row['display_name'] + ' (' + turn.metadata['member_id'] + ')'
            MEMORY.enqueue(AGENT_REF,
                attribution + ' request (not a workstation owner instruction):\n' + row['text'] +
                "\n\nDiscord Agent's accepted public report (not independent verification):\n" + result['reply'],
                source='discord:' + turn.conversation_id, identifier=turn.turn_id, timestamp=row['created_at'])

    async def _execute(self, turn, lock):
        from ..execution.executor import run_conversation
        from ..execution.adk import sessions
        from ..execution.native_turn import discard_recall
        from ..knowledge.dependencies import resolve_dependencies
        from ..knowledge.vault import resolver
        recall = None
        try:
            async with lock:
                self.store.begin(turn)
                recall = self._prefetch_recall(turn)
                res = resolver(include_system=False)
                agent = res.resolve(AGENT_REF)
                if agent is None or agent.kind != 'agent':
                    raise ValueError('The accepted Discord Bot Agent is unavailable')
                dependency = resolve_dependencies(agent, res, agent_ref=AGENT_REF)
                if dependency.get('error'):
                    raise ValueError(str(dependency['error']))
                if not self.store.turn(turn.turn_id)['memory_writeback']:
                    self._memory(turn, self.store.turn(turn.turn_id))
                # One fresh snapshot per admitted turn, outside prompt compilation.
                # Unavailable roles do not prevent ordinary conversation; effects
                # independently require fresh native permission checks.
                from . import client
                pending = asyncio.create_task(client.command({
                    'command': 'speaker_context', 'guild_id': turn.metadata['guild_id'],
                    'member_id': turn.metadata['member_id']}, timeout=3))
                try:
                    snapshot = await asyncio.shield(pending)
                except asyncio.CancelledError:
                    await asyncio.gather(pending, return_exceptions=True)
                    raise
                speaker = snapshot.get('speaker') if snapshot.get('ok') is True else None
                advisory = ({'speaker': speaker, 'advisory': True, 'labels_untrusted': True}
                            if isinstance(speaker, dict) and speaker.get('member_id') == turn.metadata['member_id']
                            else {'available': False, 'advisory': True})
                turn = replace(turn, speaker_context=advisory)
                result = await run_conversation(agent, conversation_binding=turn,
                    runtime_params={'event': 'chat.request' if turn.metadata['source'] == 'text' else 'voice.activation',
                        'request': turn.text, 'conversation_id': turn.conversation_id,
                        'reply_to_turn_id': turn.turn_id}, emit_turn_event=False, memory_recall=recall)
                reply = str(result.get('summary') or '') if result.get('status') == 'completed' else ''
                status = result.get('status')
                status = status if status in {'completed', 'failed', 'blocked', 'review', 'interrupted'} else 'failed'
                if status == 'completed' and not reply.strip():
                    status = 'failed'
                # The execution ledger owns detailed diagnostics. Discord gets
                # only accepted public dialogue or a fixed safe failure notice;
                # local paths, private Article refs and exception bodies stay local.
                outcome = {'status': status, 'reply': reply if status == 'completed' else '',
                           'summary': reply if status == 'completed' else 'This Discord request could not be completed.',
                           'conversation_id': turn.conversation_id, 'turn_id': turn.turn_id,
                           **({'run_id': result['run_id']} if result.get('run_id') else {})}
                if status != 'completed':
                    outcome['must_not_replay'] = True
                self.store.finish(turn, outcome)
                # The committed accepted reply survives optional memory delivery
                # failure; start() retries its exact idempotent delivery later.
                try:
                    self._memory(turn, self.store.turn(turn.turn_id))
                except Exception:
                    outcome['memory'] = 'pending'
                try:
                    value = sessions.view(turn.conversation_id)
                    if value:
                        self.store.rebase(turn, value['messages'])
                except Exception:
                    outcome['history_window'] = 'pending'
                return outcome
        except asyncio.CancelledError:
            outcome = {'status': 'interrupted', 'reply': '', 'must_not_replay': True,
                       'conversation_id': turn.conversation_id, 'turn_id': turn.turn_id}
            self.store.finish(turn, outcome)
            return outcome
        except Exception:
            outcome = {'status': 'failed', 'reply': '', 'must_not_replay': True,
                       'failure': 'discord_turn_failed', 'summary': 'This Discord request could not be completed.',
                       'conversation_id': turn.conversation_id, 'turn_id': turn.turn_id}
            self.store.finish(turn, outcome)
            return outcome
        finally:
            await discard_recall(recall)

    @staticmethod
    def _prefetch_recall(turn):
        """Start Bard's memory-hook recall for this exact request before compile.

        The hook recalls only after the speaker snapshot, packet compile and
        session open; starting here overlaps them, as the Executive does at
        admission. The hook adopts it only for the identical Agent and query.
        Deterministic command and music routes recall nothing, so skip them.
        """
        from ..execution.adk import sessions
        from ..execution.commands import recognize_discord_command, recognize_discord_music
        from ..execution.native_turn import recall_query
        from ..memory.hindsight import MEMORY
        tools = ('discord.control', 'media.library', 'task.complete')
        if (recognize_discord_command(turn.text, tools) is not None
                or recognize_discord_music(turn.text, tools, voice=turn.metadata['source'] != 'text') is not None):
            return None
        token = sessions.CONVERSATION_BINDING.set(turn)
        try:
            query = recall_query(turn.text, turn.conversation_id)
        finally:
            sessions.CONVERSATION_BINDING.reset(token)
        return AGENT_REF, query, asyncio.create_task(MEMORY.recall(AGENT_REF, *query),
                                                     name='obsidience-discord-recall')

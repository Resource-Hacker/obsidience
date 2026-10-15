import fs from 'node:fs/promises';
import net from 'node:net';
import { randomUUID, createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { PassThrough } from 'node:stream';
import { pathToFileURL } from 'node:url';
import { Client, GatewayIntentBits, PermissionFlagsBits, ChannelType, SlashCommandBuilder, MessageFlags } from 'discord.js';
import { AudioPlayerStatus, VoiceConnectionStatus, EndBehaviorType, NoSubscriberBehavior, StreamType,
  createAudioPlayer, createAudioResource, entersState, joinVoiceChannel } from '@discordjs/voice';
import opusBinding from '@discordjs/opus';
import { credential, loadConfig, readFrames, sendFrame, removeStaleSocket, SNOWFLAKE } from './protocol.mjs';

const REQUEST_ID = /^[A-Za-z0-9_-]{8,128}$/;
const { OpusEncoder } = opusBinding;
const ALLOWED_MENTIONS = { parse: [], repliedUser: false };
const TEXT_LIMIT = 8000;
const SPEECH_LIMIT = 4000;
const SPEECH_ERROR_CODES = new Set(['asr_failed', 'utterance_limit', 'audio_backpressure', 'stream_capacity',
  'reply_not_current', 'speech_delivery_failed', 'audio_pipeline_stopped', 'utterance_timeout', 'reply_timeout']);
const DIAGNOSTIC_COUNTS = ['received_pcm_frames', 'terminal_pcm_frames', 'stt_audio_frames',
  'stt_transcription_frames', 'vad_starts', 'vad_stops', 'queue_depth'];
const DIAGNOSTIC_FLAGS = ['available', 'input_task_done', 'input_task_failed', 'runner_done'];
const diagnosticCount = (value) => Number.isSafeInteger(value) && value >= 0 ? Math.min(value, 1_000_000_000) : null;
const log = (event) => console.log(JSON.stringify({ component: 'discord_transport', event }));
const fail = (code) => { throw new Error(code); };

export class DiscordTransport {
  constructor(config, ingressToken) {
    this.config = config;
    this.ingressToken = ingressToken;
    this.generation = randomUUID();
    this.connection = null;
    this.channel = null;
    this.speech = null;
    this.receivers = new Map();
    this.turns = new Map();
    this.recent = new Map();
    this.admissions = new Set();
    this.cancelledRequests = new Set();
    this.pendingSpeech = new Map();
    this.speechDeadlines = new Map();
    this.speechConnecting = null;
    this.media = null;
    this.cancelledMediaRequests = new Set();
    this.utterance = null;
    this.mutating = false;
    this.closing = false;
    this.lastError = null;
    this.receiveError = null;
    this.speechWorkerError = null;
    this.diagnosticRead = null;
    this.receiveCounters = { starts: 0, failures: 0, rx_packets: 0, decoded_pcm_bytes: 0,
      forwarded_pcm_bytes: 0, decoded_pcm_peak: 0, nonzero_pcm_frames: 0, wake_events: 0, transcript_events: 0 };
    this.clients = new Set();
    const intents = [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates, GatewayIntentBits.GuildMessages];
    if (config.message_content_intent) intents.push(GatewayIntentBits.MessageContent);
    this.client = new Client({ intents, allowedMentions: ALLOWED_MENTIONS });
    this.mediaPlayer = createAudioPlayer({ behaviors: { noSubscriber: NoSubscriberBehavior.Pause } });
    this.speechPlayer = createAudioPlayer({ behaviors: { noSubscriber: NoSubscriberBehavior.Pause } });
    this.mediaPlayer.on('error', () => { this.lastError = 'media_playback_failed'; this.stopMedia(); });
    this.mediaPlayer.on(AudioPlayerStatus.Idle, () => this.stopMedia());
    this.speechPlayer.on('error', (error) => {
      if (error.resource !== this.utterance?.resource) return;
      this.lastError = 'speech_playback_failed'; this.finishSpeech(false);
    });
    this.speechPlayer.on(AudioPlayerStatus.Idle, (oldState) => {
      if (oldState.resource === this.utterance?.resource) this.finishSpeech(true);
    });
    this.client.on('error', () => { this.lastError = 'discord_client_error'; log('discord_client_error'); });
    this.client.on('interactionCreate', (interaction) => { void this.interaction(interaction); });
    this.client.on('messageCreate', (message) => { void this.mention(message); });
    this.client.on('voiceStateUpdate', (oldState, state) => {
      if (state.guild.id !== this.config.guild_id) return;
      if (state.id === this.client.user?.id && this.channel && state.channelId !== this.channel.id) {
        void this.leave(); // Moderator disconnect/move invalidates every identity; never follow it.
      } else if (oldState.channelId === this.channel?.id && state.channelId !== this.channel?.id) {
        this.dropReceiver(state.id);
        this.cancelTurns(state.id);
        for (const [id, pending] of [...this.pendingSpeech]) {
          if (pending.member_id === state.id) this.cancelRequest(id, pending, pending.source);
        }
        this.sendSpeech({ type: 'reset', ...this.principal(state.id) }, false);
      }
    });
  }

  principal(memberId) {
    return { generation: this.generation, guild_id: this.config.guild_id, channel_id: this.channel?.id, member_id: memberId };
  }

  status() {
    return { name: 'Obsidience Discord Bot', display_name: this.config.bot_name, ready: this.client.isReady(),
      guild_id: this.config.guild_id, channel_id: this.channel?.id ?? null,
      voice: this.connection?.state.status ?? 'disconnected', speech_ready: !!this.speech && !this.speech.destroyed,
      generation: this.generation, receivers: this.receivers.size,
      active_turns: this.turns.size, pending_speech: this.pendingSpeech.size,
      playback: this.mediaPlayer.state.status, speech_playback: this.speechPlayer.state.status,
      media_kind: 'audio_only', video_supported: false, last_error: this.lastError,
      speech_worker_error: this.speechWorkerError, receive_error: this.receiveError, receive_counters: { ...this.receiveCounters } };
  }

  allowed(channel) {
    return channel?.guildId === this.config.guild_id && channel.type === ChannelType.GuildVoice
      && (!this.config.allowed_channel_ids.length || this.config.allowed_channel_ids.includes(channel.id));
  }

  async guild() {
    if (!this.client.isReady()) fail('discord_not_ready');
    return this.client.guilds.fetch(this.config.guild_id);
  }

  async channels() {
    const guild = await this.guild();
    const all = await guild.channels.fetch();
    return [...all.values()].filter((channel) => this.allowed(channel))
      .map((channel) => ({ id: channel.id, name: channel.name })).slice(0, 128);
  }

  sendSpeech(message, required = true) {
    try { sendFrame(this.speech, message); return true; }
    catch { if (required) fail('speech_unavailable_or_backpressure'); return false; }
  }

  async speechDiagnostics() {
    if (!this.channel || !this.speech || this.speech.destroyed) fail('speech_not_ready');
    if (this.diagnosticRead) fail('speech_diagnostics_busy');
    const principals = [...this.channel.members.values()]
      .filter((member) => !member.user.bot && member.voice.channelId === this.channel.id)
      .slice(0, 8).map((member) => this.principal(member.id));
    if (!principals.length) return { speech_diagnostics: [], complete: true };
    return new Promise((resolve) => {
      const read = { socket: this.speech, generation: this.generation,
        waiting: new Map(principals.map((principal) => [principal.member_id, principal])), results: new Map() };
      read.finish = () => {
        if (this.diagnosticRead !== read) return;
        clearTimeout(read.timer);
        this.diagnosticRead = null;
        resolve({ complete: read.waiting.size === 0,
          speech_diagnostics: principals.map((principal) => ({ member_id: principal.member_id,
            ...(read.results.get(principal.member_id) ?? { received: false }) })) });
      };
      this.diagnosticRead = read;
      read.timer = setTimeout(read.finish, 2000);
      for (const principal of principals) {
        if (!this.sendSpeech({ type: 'diagnostics', ...principal }, false)) { read.finish(); break; }
      }
    });
  }

  acceptSpeechDiagnostics(message) {
    const read = this.diagnosticRead;
    const principal = read?.waiting.get(message.member_id);
    if (!principal || read.socket !== this.speech || read.generation !== this.generation
      || !this.samePrincipal(principal, message) || !this.currentSpeaker(principal)) return;
    const result = { received: true };
    for (const key of DIAGNOSTIC_FLAGS) if (typeof message[key] === 'boolean') result[key] = message[key];
    for (const key of DIAGNOSTIC_COUNTS) {
      const value = diagnosticCount(message[key]);
      if (value !== null) result[key] = value;
    }
    const rejected = {};
    for (const key of ['possessive', 'mid_sentence']) {
      const value = diagnosticCount(message.wake_rejected?.[key]);
      if (value !== null) rejected[key] = value;
    }
    if (Object.keys(rejected).length) result.wake_rejected = rejected;
    read.results.set(message.member_id, result);
    read.waiting.delete(message.member_id);
    if (!read.waiting.size) read.finish();
  }

  async connectSpeech() {
    if (this.speech && !this.speech.destroyed) return;
    if (this.speech?.destroyed) this.speechLost(this.speech);
    if (this.speechConnecting) return this.speechConnecting;
    this.speechConnecting = this.openSpeech();
    try { await this.speechConnecting; } finally { this.speechConnecting = null; }
  }

  async openSpeech() {
    const generation = this.generation;
    const socketPath = `/run/user/${process.getuid()}/obsidience-discord-speech.sock`;
    const stat = await fs.lstat(socketPath);
    if (!stat.isSocket() || stat.uid !== process.getuid() || (stat.mode & 0o077)) fail('speech_socket_owner_or_mode_invalid');
    const socket = net.createConnection(socketPath);
    await new Promise((resolve, reject) => {
      socket.setTimeout(3000);
      socket.once('connect', resolve);
      socket.once('error', () => reject(new Error('speech_connect_failed')));
      socket.once('timeout', () => { socket.destroy(); reject(new Error('speech_connect_timeout')); });
    });
    socket.setTimeout(0);
    if (generation !== this.generation || this.closing) { socket.destroy(); fail('speech_connect_cancelled'); }
    this.speech = socket;
    readFrames(socket, (message) => { void this.speechEvent(message).catch(() => {
      this.lastError = 'speech_event_rejected';
      const pending = this.pendingSpeech.get(message.request_id);
      if (pending && this.samePrincipal(pending, message)) this.cancelRequest(message.request_id, pending, pending.source);
    }); });
    socket.on('error', () => { this.lastError = 'speech_connection_failed'; });
    socket.on('close', () => this.speechLost(socket));
    this.sendSpeech({ type: 'reset', generation: this.generation });
  }

  speechLost(socket) {
    if (this.speech !== socket) return;
    this.speech = null;
    this.lastError = 'speech_disconnected';
    this.diagnosticRead?.finish();
    this.cancelTurns();
    for (const [id, pending] of [...this.pendingSpeech]) this.cancelRequest(id, pending, pending.source);
    for (const id of [...this.receivers.keys()]) this.dropReceiver(id);
    this.finishSpeech(false);
  }

  async join(channelId) {
    if (!SNOWFLAKE.test(channelId)) fail('invalid_channel_id');
    const guild = await this.guild();
    const channel = await guild.channels.fetch(channelId);
    if (!this.allowed(channel)) fail('channel_not_allowed');
    const me = await guild.members.fetchMe();
    if (!channel.permissionsFor(me)?.has([PermissionFlagsBits.Connect, PermissionFlagsBits.Speak, PermissionFlagsBits.ViewChannel])) {
      fail('bot_missing_voice_permissions');
    }
    if (this.channel?.id === channelId && this.connection?.state.status === VoiceConnectionStatus.Ready) {
      await this.connectSpeech();
      return this.status();
    }
    await this.leave();
    const generation = this.generation;
    await this.connectSpeech();
    if (generation !== this.generation || this.closing) fail('join_cancelled');
    this.channel = channel;
    const connection = joinVoiceChannel({ channelId, guildId: guild.id, adapterCreator: guild.voiceAdapterCreator,
      selfDeaf: false, selfMute: false });
    this.connection = connection;
    connection.on('error', () => { this.lastError = 'voice_connection_failed'; void this.leave(); });
    connection.on(VoiceConnectionStatus.Disconnected, () => { void this.leave(); });
    connection.receiver.speaking.on('start', (id) => { void this.receive(id).catch((error) => this.receiveFailed('receive', error)); });
    try { await entersState(connection, VoiceConnectionStatus.Ready, 15000); }
    catch { if (this.connection === connection) await this.leave(); fail('voice_not_ready'); }
    if (generation !== this.generation || this.connection !== connection) fail('join_cancelled');
    connection.subscribe(this.mediaPlayer);
    return this.status();
  }

  dropReceiver(id) {
    const receiver = this.receivers.get(id);
    if (!receiver) return;
    this.receivers.delete(id);
    receiver.opus.destroy();
  }

  countReceive(key, amount = 1) {
    this.receiveCounters[key] = Math.min(1_000_000_000, this.receiveCounters[key] + amount);
  }

  receiveFailed(phase, error, exitCode = null) {
    this.lastError = 'receive_failed';
    this.countReceive('failures');
    const name = error?.constructor?.name;
    // Never emit error messages or raw stack lines: they can contain content.
    const lines = [];
    for (const frame of String(error?.stack ?? '').split('\n').slice(1, 24)) {
      const offset = frame.indexOf(`${import.meta.url}:`);
      if (offset < 0) continue;
      const location = frame.slice(offset + import.meta.url.length + 1).match(/^(\d+):\d+\)?$/);
      if (location) lines.push(Number(location[1]));
    }
    this.receiveError = { phase, exception_class: typeof name === 'string' && /^[A-Za-z_][A-Za-z0-9_]{0,79}$/.test(name) ? name : null,
      file: 'bot.mjs', lines: lines.slice(0, 8), ...(Number.isInteger(exitCode) ? { exit_code: exitCode } : {}) };
    console.log(JSON.stringify({ component: 'discord_transport', event: 'receive_failed', ...this.receiveError }));
  }

  async receive(memberId) {
    if (!this.connection || !this.channel || this.receivers.has(memberId) || this.receivers.size >= 8) return;
    const generation = this.generation;
    let member = this.channel.members.get(memberId);
    if (!member || member.user.bot || member.voice.channelId !== this.channel.id) return;
    let phase = 'connect_speech';
    let opus;
    try {
      // Recover only on a real speaking event. Never replay buffered requests.
      if (!this.speech || this.speech.destroyed) await this.connectSpeech();
      if (generation !== this.generation || !this.connection || !this.channel || this.closing) return;
      member = this.channel.members.get(memberId);
      if (!member || member.user.bot || member.voice.channelId !== this.channel.id || this.receivers.has(memberId)) return;
      const principal = this.principal(memberId);
      phase = 'opus_decoder';
      // libopus converts encoded Discord audio directly to the ASR format.
      // Preserve each RTC packet's arrival cadence; no resampler pipe buffering.
      const decoder = new OpusEncoder(16000, 1);
      phase = 'subscribe';
      opus = this.connection.receiver.subscribe(memberId, { end: { behavior: EndBehaviorType.AfterSilence, duration: 300 } });
      const record = { opus };
      this.receivers.set(memberId, record);
      this.countReceive('starts');
      const current = () => generation === this.generation && this.receivers.get(memberId) === record;
      const destroy = () => { if (current()) this.dropReceiver(memberId); };
      const rejected = (at, error) => {
        if (!current()) return;
        this.receiveFailed(at, error);
        destroy();
      };
      opus.on('error', (error) => rejected('opus_stream', error));
      opus.on('data', (packet) => {
        if (!current()) return;
        this.countReceive('rx_packets');
        let at = 'opus_decode';
        try {
          const pcm = decoder.decode(packet);
          this.countReceive('decoded_pcm_bytes', pcm.length);
          // Opus packets hold at most 120 ms: 3,840 mono s16 bytes at 16 kHz.
          if (!pcm.length || pcm.length % 2 || pcm.length > 3840) fail('invalid_decoded_pcm');
          let peak = 0;
          for (let offset = 0; offset < pcm.length; offset += 2) peak = Math.max(peak, Math.abs(pcm.readInt16LE(offset)));
          this.receiveCounters.decoded_pcm_peak = Math.max(this.receiveCounters.decoded_pcm_peak, peak);
          if (peak) this.countReceive('nonzero_pcm_frames');
          at = 'speech_send';
          this.sendSpeech({ type: 'audio', ...principal, pcm: pcm.toString('base64'),
            sample_rate: 16000, channels: 1, format: 's16le' });
          this.countReceive('forwarded_pcm_bytes', pcm.length);
        } catch (error) { rejected(at, error); }
      });
      opus.on('end', () => {
        if (!current()) return;
        this.receivers.delete(memberId);
        opus.destroy();
      });
    } catch (error) {
      this.receiveFailed(phase, error);
      opus?.destroy();
    }
  }

  cancelRequest(requestId, principal = null, source = null) {
    const turn = this.turns.get(requestId);
    const pending = this.pendingSpeech.get(requestId);
    principal = turn?.principal ?? pending ?? principal;
    source = turn?.source ?? pending?.source ?? source;
    if (principal) principal = Object.fromEntries(['generation', 'guild_id', 'channel_id', 'member_id'].map((key) => [key, principal[key]]));
    turn?.controller.abort();
    this.turns.delete(requestId);
    this.pendingSpeech.delete(requestId);
    clearTimeout(this.speechDeadlines.get(requestId));
    this.speechDeadlines.delete(requestId);
    const first = !this.cancelledRequests.has(requestId);
    this.cancelledRequests.add(requestId);
    while (this.cancelledRequests.size > 256) this.cancelledRequests.delete(this.cancelledRequests.values().next().value);
    if (this.utterance?.request_id === requestId) this.finishSpeech(false);
    if (!first) return;
    if (!principal) return;
    if (principal.generation === this.generation) this.sendSpeech({ type: 'cancel', ...principal, request_id: requestId }, false);
    if (source !== 'voice' && source !== 'text') return;
    // Abort alone only closes HTTP; cancellation must reach the same Agent owner.
    void fetch('http://127.0.0.1:8765/api/discord/cancel', {
        method: 'POST', signal: AbortSignal.timeout(4000),
        headers: { Authorization: `Bearer ${this.ingressToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...principal, request_id: requestId, source }),
    }).then((response) => {
        if (!response.ok) this.lastError = 'agent_cancel_not_confirmed';
        return response.body?.cancel();
    }).catch(() => { this.lastError = 'agent_cancel_not_confirmed'; });
  }

  cancelTurns(memberId = null, preserveRequestId = null) {
    for (const [requestId, turn] of [...this.turns]) {
      if (requestId !== preserveRequestId && (!memberId || turn.principal.member_id === memberId)) this.cancelRequest(requestId);
    }
  }

  stop(originRequestId = null, memberId = null) {
    if (originRequestId !== null) {
      const origin = this.turns.get(originRequestId);
      if (!REQUEST_ID.test(originRequestId) || !origin || origin.controller.signal.aborted
        || origin.principal.guild_id !== this.config.guild_id || origin.principal.member_id !== memberId) fail('stop_origin_not_current');
      // The Agent can stop current output and still return this exact turn's
      // ordinary reply. Its speech owner/request must survive that receipt.
      this.cancelTurns(null, originRequestId);
      for (const [id, pending] of [...this.pendingSpeech]) this.cancelRequest(id, pending, pending.source);
      this.finishSpeech(false);
      this.stopMedia();
      return { ...this.status(), preserved_origin_turn: true };
    }
    this.cancelTurns();
    for (const [id, pending] of [...this.pendingSpeech]) this.cancelRequest(id, pending, pending.source);
    this.generation = randomUUID();
    this.diagnosticRead?.finish();
    this.finishSpeech(false);
    this.stopMedia();
    for (const id of [...this.receivers.keys()]) this.dropReceiver(id);
    this.sendSpeech({ type: 'reset', generation: this.generation }, false);
    return this.status(); // Speaking listener remains armed; next utterance uses fresh generation.
  }

  async leave() {
    this.stop();
    const connection = this.connection;
    this.connection = null;
    this.channel = null;
    this.speech?.destroy();
    this.speech = null;
    if (connection && connection.state.status !== VoiceConnectionStatus.Destroyed) connection.destroy();
    return this.status();
  }

  async turn(text, principal, requestId, source) {
    if (typeof text !== 'string' || !text.trim() || text.length > TEXT_LIMIT) fail('invalid_text');
    if (this.turns.size) fail('agent_busy');
    if (!REQUEST_ID.test(requestId)) fail('invalid_request_id');
    const admission = `${source}:${requestId}`;
    if (this.admissions.has(admission)) fail('turn_already_admitted');
    this.admissions.add(admission);
    while (this.admissions.size > 256) this.admissions.delete(this.admissions.values().next().value);
    const controller = new AbortController();
    const turn = { controller, principal, source };
    this.turns.set(requestId, turn);
    const timeout = setTimeout(() => this.cancelRequest(requestId, principal, source), 120000);
    const generation = this.generation;
    try {
      const response = await fetch('http://127.0.0.1:8765/api/discord/turns', {
        method: 'POST', signal: controller.signal,
        headers: { Authorization: `Bearer ${this.ingressToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...principal, request_id: requestId, text, source }),
      });
      if (!response.ok) fail('agent_ingress_rejected');
      const chunks = [];
      let size = 0;
      for await (const chunk of response.body) {
        size += chunk.length;
        if (size > 65536) { controller.abort(); fail('agent_reply_too_large'); }
        chunks.push(Buffer.from(chunk));
      }
      const result = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      if (generation !== this.generation || controller.signal.aborted) fail('turn_cancelled');
      if (typeof result.reply !== 'string' || result.reply.length > 16000) fail('invalid_agent_reply');
      if (result.reply.length > SPEECH_LIMIT) {
        // One bounded reply, ending on a complete Unicode code point.
        result.reply = result.reply.slice(0, SPEECH_LIMIT - 1).replace(/[\uD800-\uDBFF]$/u, '') + '…';
      }
      return result;
    } catch (error) {
      this.cancelRequest(requestId, principal, source);
      throw error;
    } finally {
      clearTimeout(timeout);
      if (this.turns.get(requestId) === turn) this.turns.delete(requestId);
    }
  }

  async speechEvent(message) {
    if (message.generation !== this.generation || message.guild_id !== this.config.guild_id
      || !this.channel || message.channel_id !== this.channel.id || !SNOWFLAKE.test(message.member_id)) return;
    const principal = this.principal(message.member_id);
    // Diagnostics intentionally has no turn request_id and never enters dialogue.
    if (message.type === 'diagnostics') { this.acceptSpeechDiagnostics(message); return; }
    if (message.type === 'error') {
      if (this.currentSpeaker(principal)) this.speechWorkerError = SPEECH_ERROR_CODES.has(message.code) ? message.code : 'unclassified_speech_worker_error';
      this.lastError = 'speech_worker_error';
      const pending = this.pendingSpeech.get(message.request_id);
      const turn = this.turns.get(message.request_id);
      if ((pending && this.samePrincipal(pending, principal)) || (turn && this.samePrincipal(turn.principal, principal))) {
        this.cancelRequest(message.request_id, principal, 'voice');
      }
      return;
    }
    if (!REQUEST_ID.test(message.request_id ?? '')) return;
    if (this.cancelledRequests.has(message.request_id)) return;
    if (message.type === 'wake') { this.countReceive('wake_events'); return; }
    if (message.type === 'transcript') {
      if (this.admissions.has(`voice:${message.request_id}`)) return;
      const member = this.channel.members.get(message.member_id);
      if (!member || member.user.bot || member.voice.channelId !== this.channel.id) return;
      this.countReceive('transcript_events');
      try {
        const result = await this.turn(message.text, principal, message.request_id, 'voice');
        if (result.status !== 'completed' || !result.reply.trim()) {
          this.sendSpeech({ type: 'cancel', ...principal, request_id: message.request_id }, false); return;
        }
        const memberNow = this.channel?.members.get(message.member_id);
        if (!memberNow || memberNow.voice.channelId !== principal.channel_id || !this.samePrincipal(principal, this.principal(message.member_id))) fail('speaker_not_current');
        this.requestSpeech(principal, message.request_id, result.reply, 'voice');
      } catch { this.cancelRequest(message.request_id, principal, 'voice'); this.lastError = 'voice_turn_failed'; }
    } else if (message.type === 'speech_audio') {
      const pending = this.pendingSpeech.get(message.request_id);
      if (!pending || !this.samePrincipal(pending, principal) || !this.currentSpeaker(principal)) return;
      if (message.sample_rate !== 24000 || typeof message.pcm !== 'string' || message.pcm.length > 60000
        || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(message.pcm)) fail('invalid_speech_audio');
      if (!this.utterance) this.startSpeech(principal, message.request_id);
      const utterance = this.utterance;
      if (utterance.request_id !== message.request_id || utterance.member_id !== message.member_id) return;
      const pcm = Buffer.from(message.pcm, 'base64');
      if (pcm.length % 2 || utterance.input.writableLength > 96000) fail('speech_audio_backpressure');
      utterance.input.write(pcm);
    } else if (message.type === 'speech_end') {
      const pending = this.pendingSpeech.get(message.request_id);
      if (!pending || !this.samePrincipal(pending, principal) || !this.currentSpeaker(principal)) return;
      if (this.utterance?.request_id === message.request_id && this.samePrincipal(this.utterance, principal)) this.utterance.input.end();
      else this.cancelRequest(message.request_id, pending, pending.source);
    }
  }

  samePrincipal(a, b) {
    return ['generation', 'guild_id', 'channel_id', 'member_id'].every((key) => a[key] === b[key]);
  }

  currentSpeaker(principal) {
    if (principal.generation !== this.generation || principal.guild_id !== this.config.guild_id || principal.channel_id !== this.channel?.id) return false;
    const member = this.channel.members.get(principal.member_id);
    return !!member && member.voice.channelId === principal.channel_id;
  }

  requestSpeech(principal, requestId, text, source) {
    if (this.cancelledRequests.has(requestId) || this.pendingSpeech.size || !this.currentSpeaker(principal)) fail('speech_not_current_or_busy');
    if (text.length > SPEECH_LIMIT) fail('speech_text_too_large');
    this.pendingSpeech.set(requestId, { ...principal, source });
    this.speechDeadlines.set(requestId, setTimeout(() => this.cancelRequest(requestId, principal, source), 120000));
    try { this.sendSpeech({ type: 'speak', ...principal, source: source === 'owner' ? 'owner' : undefined, request_id: requestId, text }); }
    catch (error) { this.cancelRequest(requestId, principal, source); throw error; }
  }

  startSpeech(principal, requestId) {
    if (!this.connection || this.utterance) fail('voice_not_ready_or_speaking');
    const input = new PassThrough({ highWaterMark: 48000 });
    const child = spawn('/usr/bin/ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1', '-filter_threads', '1',
      '-f', 's16le', '-ar', '24000', '-ac', '1', '-i', 'pipe:0', '-f', 's16le', '-ar', '48000', '-ac', '2', 'pipe:1'],
    { stdio: ['pipe', 'pipe', 'ignore'], env: { PATH: '/usr/bin', LANG: 'C' } });
    this.utterance = { ...principal, source: this.pendingSpeech.get(requestId)?.source, request_id: requestId, input, process: child,
      resumeMedia: !!this.media && this.mediaPlayer.state.status === AudioPlayerStatus.Playing };
    this.mediaPlayer.pause();
    input.pipe(child.stdin);
    const failed = () => { if (this.utterance?.process === child) this.finishSpeech(false); };
    input.on('error', failed);
    child.on('error', failed);
    child.stdin.on('error', failed);
    child.stdout.on('error', failed);
    child.on('close', (code) => { if (code && this.utterance?.process === child) this.finishSpeech(false); });
    this.connection.subscribe(this.speechPlayer);
    this.utterance.resource = createAudioResource(child.stdout, { inputType: StreamType.Raw });
    this.speechPlayer.play(this.utterance.resource);
  }

  finishSpeech(played) {
    const utterance = this.utterance;
    if (!utterance) return;
    this.utterance = null;
    this.speechPlayer.stop(true);
    utterance.input.destroy();
    utterance.process.stdin.destroy();
    utterance.process.stdout.destroy();
    utterance.process.kill('SIGKILL');
    if (utterance.generation === this.generation) {
      this.pendingSpeech.delete(utterance.request_id);
      clearTimeout(this.speechDeadlines.get(utterance.request_id));
      this.speechDeadlines.delete(utterance.request_id);
      if (!played) this.cancelRequest(utterance.request_id, utterance, utterance.source);
      else this.sendSpeech({ type: 'played', generation: utterance.generation,
        guild_id: utterance.guild_id, channel_id: utterance.channel_id, member_id: utterance.member_id,
        request_id: utterance.request_id }, false);
      if (this.connection) this.connection.subscribe(this.mediaPlayer);
      if (utterance.resumeMedia && this.media?.generation === this.generation) this.mediaPlayer.unpause();
    }
  }

  stopMedia() {
    const media = this.media;
    this.media = null;
    this.mediaPlayer.stop(true);
    if (media) {
      media.process.stdout.destroy(); media.process.kill('SIGKILL');
      void media.handle.close().catch(() => {});
    }
  }

  cancelMedia(requestId) {
    if (!REQUEST_ID.test(requestId ?? '')) fail('playback_request_id_required');
    this.cancelledMediaRequests.add(requestId);
    while (this.cancelledMediaRequests.size > 256) this.cancelledMediaRequests.delete(this.cancelledMediaRequests.values().next().value);
    const stopped = this.media?.requestId === requestId;
    if (stopped) this.stopMedia();
    return { playback_request_id: requestId, playback_stopped: stopped,
      delivery: stopped ? 'audio_playback_stopped' : 'media_cancellation_registered', ...this.status() };
  }

  async play(message) {
    if (!this.connection || !this.channel || this.connection.state.status !== VoiceConnectionStatus.Ready) fail('voice_not_ready');
    if (this.utterance) fail('speech_busy');
    const { path: filename, file_identity: identity, expires_at_ms: expiresAt, request_id: requestId } = message;
    const identityFields = ['dev', 'ino', 'size', 'mtime_ns'];
    if (!identity || typeof identity !== 'object' || Array.isArray(identity)
      || Object.keys(identity).length !== identityFields.length
      || identityFields.some((key) => typeof identity[key] !== 'string' || !/^[0-9]{1,30}$/.test(identity[key]))) fail('media_file_identity_required');
    if (!Number.isSafeInteger(expiresAt) || expiresAt > Date.now() + 15000) fail('invalid_media_deadline');
    const current = () => !this.cancelledMediaRequests.has(requestId) && Date.now() < expiresAt;
    if (!current()) fail('media_request_expired_or_cancelled');
    // The Harness retains its admitted source FD until our Playing receipt.
    // Open that descriptor once, then pass our own held descriptor to FFmpeg.
    if (typeof filename !== 'string' || !/^\/proc\/\d+\/fd\/\d+$/.test(filename)) fail('admitted_media_descriptor_required');
    const generation = this.generation;
    const handle = await fs.open(filename, 'r');
    let stat;
    try { stat = await handle.stat({ bigint: true }); }
    catch (error) { await handle.close(); throw error; }
    if (!stat.isFile() || stat.dev.toString() !== identity.dev || stat.ino.toString() !== identity.ino
      || stat.size.toString() !== identity.size || stat.mtimeNs.toString() !== identity.mtime_ns) {
      await handle.close(); fail('admitted_media_identity_changed');
    }
    if (generation !== this.generation || this.utterance || this.pendingSpeech.size || !current()) {
      await handle.close(); fail('media_request_expired_or_cancelled');
    }
    this.stopMedia();
    const child = spawn('/usr/bin/ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1', '-filter_threads', '1',
      '-protocol_whitelist', 'file,pipe', '-i', '/proc/self/fd/3', '-vn', '-f', 's16le', '-ar', '48000', '-ac', '2', 'pipe:1'],
    { stdio: ['ignore', 'pipe', 'ignore', handle.fd], env: { PATH: '/usr/bin', LANG: 'C' } });
    this.media = { process: child, generation, handle, requestId };
    child.on('error', () => { if (this.media?.process === child) this.stopMedia(); });
    child.stdout.on('error', () => { if (this.media?.process === child) this.stopMedia(); });
    child.on('close', (code) => { if (code && this.media?.process === child) this.stopMedia(); });
    if (!current()) { this.stopMedia(); fail('media_request_expired_or_cancelled'); }
    this.connection.subscribe(this.mediaPlayer);
    this.mediaPlayer.play(createAudioResource(child.stdout, { inputType: StreamType.Raw }));
    try { await entersState(this.mediaPlayer, AudioPlayerStatus.Playing, Math.min(5000, Math.max(1, expiresAt - Date.now()))); }
    catch { if (this.media?.process === child) this.stopMedia(); fail('audio_playback_not_started'); }
    if (generation !== this.generation || this.media?.process !== child || !current()) {
      if (this.media?.process === child) this.stopMedia();
      fail('play_cancelled');
    }
    return { delivery: 'audio_playback_started', playback_request_id: requestId, media_kind: 'audio_only', video_supported: false, ...this.status() };
  }

  async command(message) {
    const readOnly = ['status', 'channels', 'speech_diagnostics'].includes(message.command);
    if (!readOnly && !REQUEST_ID.test(message.request_id ?? '')) fail('request_id_required');
    const fingerprint = createHash('sha256').update(JSON.stringify(message)).digest('hex');
    if (!readOnly && this.recent.has(message.request_id)) {
      const previous = this.recent.get(message.request_id);
      if (previous.fingerprint !== fingerprint) fail('request_id_reused');
      return previous.result ?? { ok: false, status: 'in_progress', request_id: message.request_id };
    }
    if (this.mutating && !readOnly && !['stop', 'leave', 'cancel_media'].includes(message.command)) fail('transport_busy');
    if (!readOnly) {
      this.recent.set(message.request_id, { fingerprint });
      while (this.recent.size > 256) this.recent.delete(this.recent.keys().next().value);
    }
    const ownsMutation = !readOnly && !this.mutating;
    if (ownsMutation) this.mutating = true;
    let result;
    try {
      if (message.guild_id !== undefined && message.guild_id !== this.config.guild_id) fail('guild_not_allowed');
      if (message.member_id !== undefined && message.command !== 'cancel_media') {
        if (!SNOWFLAKE.test(message.member_id)) fail('invalid_member_id');
        const guild = await this.guild();
        const member = await guild.members.fetch(message.member_id);
        if (message.command === 'join') {
          const target = message.channel_id ?? member.voice.channelId;
          if (!target || target !== member.voice.channelId) fail('join_requires_invoker_channel');
          if (!member.voice.channel?.permissionsFor(member)?.has([PermissionFlagsBits.Connect, PermissionFlagsBits.Speak])) fail('invoker_missing_voice_permissions');
          if (this.channel && this.channel.id !== target && !member.permissions.has(PermissionFlagsBits.ManageGuild)) fail('manage_guild_required');
          message = { ...message, channel_id: target };
        } else if (['play', 'pause', 'resume', 'stop', 'say'].includes(message.command)) {
          if (!this.channel || member.voice.channelId !== this.channel.id) fail('invoker_not_in_joined_channel');
        } else if (message.command === 'leave' && !member.permissions.has(PermissionFlagsBits.ManageGuild)) fail('manage_guild_required');
      }
      let value;
      switch (message.command) {
        case 'status': value = this.status(); break;
        case 'channels': value = { channels: await this.channels() }; break;
        case 'speech_diagnostics':
          if (Object.keys(message).some((key) => !['command', 'request_id'].includes(key))) fail('owner_diagnostics_only');
          value = await this.speechDiagnostics(); break;
        case 'join': value = await this.join(message.channel_id); break;
        case 'leave': value = await this.leave(); break;
        case 'stop': value = this.stop(message.origin_request_id ?? null, message.member_id ?? null); break;
        case 'pause':
          if (this.utterance) this.utterance.resumeMedia = false;
          value = { paused: this.mediaPlayer.pause(), ...this.status() }; break;
        case 'resume':
          if (this.utterance) { this.utterance.resumeMedia = true; value = this.status(); }
          else value = { resumed: this.mediaPlayer.unpause(), ...this.status() };
          break;
        case 'play': value = await this.play(message); break;
        case 'cancel_media': value = this.cancelMedia(message.playback_request_id); break;
        case 'say': {
          if (!this.channel || !this.speech) fail('voice_not_ready');
          if (this.utterance || this.pendingSpeech.size || this.turns.size) fail('speech_busy');
          if (typeof message.text !== 'string' || !message.text.trim() || message.text.length > SPEECH_LIMIT) fail('invalid_text');
          const memberId = message.member_id ?? this.client.user.id;
          if (!SNOWFLAKE.test(memberId)) fail('invalid_member_id');
          this.requestSpeech(this.principal(memberId), message.request_id, message.text, 'owner');
          value = { delivery: 'speech_requested', request_id: message.request_id, ...this.status() }; break;
        }
        default: fail('unknown_command');
      }
      result = { ok: true, request_id: message.request_id ?? null, ...value };
    } catch (error) {
      // Keep transport-generated codes only; never log Discord/HTTP exception objects or credentials.
      const code = /^[a-z_]{3,80}$/.test(error.message) ? error.message : 'transport_command_failed';
      result = { ok: false, request_id: message.request_id ?? null, error: code, delivery: 'not_confirmed' };
    } finally { if (ownsMutation) this.mutating = false; }
    if (!readOnly) this.recent.set(message.request_id, { fingerprint, result });
    return result;
  }

  async interaction(interaction) {
    if (!interaction.isChatInputCommand() || interaction.guildId !== this.config.guild_id) return;
    const name = interaction.commandName;
    if (!['join', 'leave', 'status', 'ask', 'stop'].includes(name)) return;
    try {
      await interaction.deferReply({ flags: MessageFlags.Ephemeral });
      const guild = await this.guild();
      const member = await guild.members.fetch(interaction.user.id);
      const manager = member.permissions.has(PermissionFlagsBits.ManageGuild);
      if (name === 'ask') {
        const result = await this.turn(interaction.options.getString('text', true),
          { guild_id: guild.id, channel_id: interaction.channelId, member_id: member.id, generation: this.generation },
          interaction.id, 'text');
        await interaction.editReply({ content: (result.reply || 'No completed reply.').slice(0, 1900), allowedMentions: ALLOWED_MENTIONS });
        return;
      }
      if (name === 'join') {
        const channel = member.voice.channel;
        if (!channel || !channel.permissionsFor(member)?.has([PermissionFlagsBits.Connect, PermissionFlagsBits.Speak])) fail('join_your_voice_channel_first');
        if (this.channel && this.channel.id !== channel.id && !manager) fail('manage_guild_required_to_move_bot');
        const result = await this.command({ command: 'join', request_id: interaction.id, channel_id: channel.id });
        await interaction.editReply({ content: JSON.stringify(result).slice(0, 1900), allowedMentions: ALLOWED_MENTIONS });
      } else {
        if (['leave', 'stop'].includes(name) && !manager) fail('manage_guild_required');
        const result = await this.command({ command: name, request_id: interaction.id });
        await interaction.editReply({ content: JSON.stringify(result).slice(0, 1900), allowedMentions: ALLOWED_MENTIONS });
      }
    } catch {
      if (interaction.deferred) await interaction.editReply({ content: 'The request could not be completed. Check Squanchbot status or your channel permissions.', allowedMentions: ALLOWED_MENTIONS }).catch(() => {});
    }
  }

  async mention(message) {
    if (message.guildId !== this.config.guild_id || message.author.bot || !message.mentions.has(this.client.user)) return;
    if (this.config.allowed_channel_ids.length && !this.config.allowed_channel_ids.includes(message.channelId)) return;
    const text = message.content.replace(new RegExp(`<@!?${this.client.user.id}>`, 'g'), '').trim();
    if (!text) return;
    try {
      const result = await this.turn(text, { guild_id: message.guildId, channel_id: message.channelId,
        member_id: message.author.id, generation: this.generation }, message.id, 'text');
      await message.reply({ content: (result.reply || 'No completed reply.').slice(0, 1900), allowedMentions: ALLOWED_MENTIONS });
    } catch { /* No replay of an uncertain send. Slash status remains available. */ }
  }

  async start(token) {
    const ready = new Promise((resolve) => this.client.once('clientReady', resolve));
    this.startupPhase = 'gateway_login';
    await this.client.login(token);
    await ready;
    if (this.client.application.id !== this.config.application_id || !this.client.user.bot) fail('official_bot_identity_mismatch');
    this.startupPhase = 'command_registration';
    const guild = await this.guild();
    const commands = ['join', 'leave', 'status', 'stop'].map((name) => new SlashCommandBuilder()
      .setName(name).setDescription(`${this.config.bot_name}: ${name}`));
    commands.push(new SlashCommandBuilder().setName('ask').setDescription(`Ask ${this.config.bot_name}`)
      .addStringOption((option) => option.setName('text').setDescription('Your question').setRequired(true).setMaxLength(6000)));
    await guild.commands.set(commands.map((command) => command.toJSON()));
    if (guild.members.me?.nickname !== this.config.bot_name) await guild.members.me.setNickname(this.config.bot_name).catch(() => { this.lastError = 'nickname_permission_missing'; });
    this.startupPhase = 'control_socket';
    await this.listenControl();
    log('ready_disconnected');
  }

  async listenControl() {
    const runtime = `/run/user/${process.getuid()}`;
    const directory = await fs.stat(runtime);
    if (directory.uid !== process.getuid() || (directory.mode & 0o077)) fail('private_runtime_directory_required');
    this.controlPath = `${runtime}/obsidience-discord-bot.sock`;
    await removeStaleSocket(this.controlPath);
    this.server = net.createServer((socket) => {
      if (this.clients.size >= 8) { socket.destroy(); return; }
      this.clients.add(socket);
      socket.setTimeout(20000, () => socket.destroy());
      socket.on('error', () => {});
      socket.on('close', () => this.clients.delete(socket));
      let used = false;
      readFrames(socket, (message) => {
        if (used) { socket.destroy(); return; }
        used = true;
        void this.command(message).then((result) => { if (!socket.destroyed) { sendFrame(socket, result); socket.end(); } })
          .catch(() => { if (!socket.destroyed) socket.end(`${JSON.stringify({ ok: false, error: 'invalid_request' })}\n`); });
      });
    });
    // UMask=0077 is also required in the unit; set it here for non-systemd invocation.
    process.umask(0o077);
    await new Promise((resolve, reject) => { this.server.once('error', reject); this.server.listen(this.controlPath, resolve); });
    await fs.chmod(this.controlPath, 0o600);
    this.controlIdentity = await fs.lstat(this.controlPath);
  }

  async close() {
    if (this.closing) return;
    this.closing = true;
    await this.leave();
    for (const socket of this.clients) socket.destroy();
    if (this.server) await new Promise((resolve) => this.server.close(resolve));
    const stat = this.controlPath ? await fs.lstat(this.controlPath).catch(() => null) : null;
    if (stat && stat.dev === this.controlIdentity?.dev && stat.ino === this.controlIdentity?.ino) await fs.unlink(this.controlPath);
    this.client.destroy();
  }
}

async function main() {
  const config = await loadConfig(process.env.OBSIDIENCE_DISCORD_CONFIG);
  if (config.enabled !== true) fail('discord_disabled');
  const transport = new DiscordTransport(config, await credential('discord-ingress-token'));
  process.once('SIGTERM', () => { void transport.close().then(() => process.exit(0)); });
  process.once('SIGINT', () => { void transport.close().then(() => process.exit(0)); });
  try { await transport.start(await credential('discord-bot-token')); }
  catch (error) {
    console.log(JSON.stringify({ component: 'discord_transport', event: 'startup_failed',
      phase: transport.startupPhase ?? 'configuration',
      code: Number.isSafeInteger(error.code) ? error.code : null }));
    await transport.close(); throw new Error('discord_start_failed');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => { log('startup_failed'); process.exitCode = 1; });
}

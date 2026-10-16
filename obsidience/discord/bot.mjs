import fs from 'node:fs/promises';
import net from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { PassThrough, Readable } from 'node:stream';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Client, GatewayIntentBits, PermissionFlagsBits, ChannelType, SlashCommandBuilder, MessageFlags } from 'discord.js';
import { AudioPlayerStatus, VoiceConnectionStatus, EndBehaviorType, NoSubscriberBehavior, StreamType,
  createAudioPlayer, createAudioResource, entersState, joinVoiceChannel } from '@discordjs/voice';
import opusBinding from '@discordjs/opus';
import { credential, loadConfig, readFrames, sendFrame, removeStaleSocket, SNOWFLAKE } from './protocol.mjs';
import { VoiceSamples } from './samples.mjs';

const REQUEST_ID = /^[A-Za-z0-9_-]{8,128}$/;
const { OpusEncoder } = opusBinding;
const ALLOWED_MENTIONS = { parse: [], repliedUser: false };
const TEXT_LIMIT = 8000;
const SPEECH_LIMIT = 4000;
const TTS_FRAME_BYTES = 24_000 * 2 * 0.020; // 480 mono S16 samples, exactly 20 ms.
const TTS_PREBUFFER_FRAMES = 20; // Two 200 ms speech-owner chunks.
const TTS_MAX_BUFFER_FRAMES = 100; // Two seconds, matching the former PCM bound.
const TTS_GAIN = 2; // +6.02 dB; preserve dynamics, protect peaks before Opus.
const TTS_PEAK_KNEE = 0.85;
const TTS_PEAK_CEILING = 0.95;
const SPEECH_ERROR_CODES = new Set(['asr_failed', 'utterance_limit', 'audio_backpressure', 'stream_capacity',
  'reply_not_current', 'speech_delivery_failed', 'audio_pipeline_stopped', 'utterance_timeout', 'reply_timeout']);
const DIAGNOSTIC_COUNTS = ['received_pcm_frames', 'terminal_pcm_frames', 'stt_audio_frames',
  'stt_transcription_frames', 'vad_starts', 'vad_stops', 'queue_depth', 'queue_high_water',
  'skipped_terminal_frames', 'error_count', 'failed_queue_depth'];
const DIAGNOSTIC_FLAGS = ['available', 'input_task_done', 'input_task_failed', 'runner_done', 'blocked'];
const diagnosticCount = (value) => Number.isSafeInteger(value) && value >= 0 ? Math.min(value, 1_000_000_000) : null;
const log = (event) => console.log(JSON.stringify({ component: 'discord_transport', event }));
const fail = (code) => { throw new Error(code); };

// These installation assets stay outside source control and have the Executive's
// existing gain. Decode only their bounded, uncompressed native PCM WAV envelope.
export async function loadCueAssets(root = new URL('../state/realtime-cues/', import.meta.url)) {
  const assets = new Map();
  for (const name of ['ready', 'accepted', 'follow_up', 'complete', 'cancel', 'error']) {
    try {
      const handle = await fs.open(new URL(`${name}.wav`, root), 'r');
      let wav;
      try {
        const info = await handle.stat();
        if (!info.isFile() || info.size > 250000) continue;
        wav = await handle.readFile();
      } finally { await handle.close(); }
      if (wav.length < 44 || wav.toString('ascii', 0, 4) !== 'RIFF' || wav.toString('ascii', 8, 12) !== 'WAVE') continue;
      let format = false;
      let pcm;
      for (let at = 12; at + 8 <= wav.length;) {
        const id = wav.toString('ascii', at, at + 4);
        const size = wav.readUInt32LE(at + 4);
        at += 8;
        if (at + size > wav.length) break;
        if (id === 'fmt ' && size >= 16) format = wav.readUInt16LE(at) === 1
          && wav.readUInt16LE(at + 2) === 1 && wav.readUInt32LE(at + 4) === 24000
          && wav.readUInt16LE(at + 12) === 2 && wav.readUInt16LE(at + 14) === 16;
        if (id === 'data') pcm = wav.subarray(at, at + size);
        at += size + (size % 2);
      }
      if (!format || !pcm?.length || pcm.length % 2 || pcm.length > 24000 * 2 * 4) continue;
      if (name === 'ready' || name === 'follow_up') {
        let start = 0;
        while (start < pcm.length && pcm.readInt16LE(start) === 0) start += 2;
        pcm = pcm.subarray(start);
      }
      if (!pcm.length) continue;
      const encoder = new OpusEncoder(24000, 1);
      const packets = [];
      for (let at = 0; at < pcm.length; at += TTS_FRAME_BYTES) {
        const frame = Buffer.alloc(TTS_FRAME_BYTES);
        pcm.copy(frame, 0, at, Math.min(at + TTS_FRAME_BYTES, pcm.length));
        packets.push(Buffer.from(encoder.encode(frame)));
      }
      packets.push(Buffer.from(encoder.encode(Buffer.alloc(TTS_FRAME_BYTES))));
      assets.set(name, packets);
    } catch { /* Optional missing/invalid clips never prevent speech. */ }
  }
  return assets;
}

export class DiscordTransport {
  constructor(config, ingressToken) {
    this.config = config;
    this.samples = new VoiceSamples(config.voice_samples, config.guild_id, log);
    this.ingressToken = ingressToken;
    this.generation = randomUUID();
    this.connection = null;
    this.restoreSpeaking = null;
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
    this.pendingMedia = null;
    this.mediaCleanups = new Set();
    this.cancelledMediaRequests = new Set();
    this.utterance = null;
    this.cue = null;
    this.pendingCue = null;
    this.voiceRequest = null;
    this.cueAssets = new Map();
    this.mutating = false;
    this.closing = false;
    this.lastError = null;
    this.receiveError = null;
    this.speechWorkerError = null;
    this.diagnosticRead = null;
    this.wakeCalibration = null;
    this.voiceProbe = null;
    this.voiceTiming = null;
    this.receiveCounters = { starts: 0, failures: 0, rx_packets: 0, decoded_pcm_bytes: 0,
      forwarded_pcm_bytes: 0, decoded_pcm_peak: 0, nonzero_pcm_frames: 0, invalid_opus_packets: 0,
      wake_events: 0, transcript_events: 0 };
    this.clients = new Set();
    const intents = [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates, GatewayIntentBits.GuildMessages];
    if (config.message_content_intent) intents.push(GatewayIntentBits.MessageContent);
    this.client = new Client({ intents, allowedMentions: ALLOWED_MENTIONS });
    this.mediaPlayer = createAudioPlayer({ behaviors: { noSubscriber: NoSubscriberBehavior.Pause } });
    this.speechPlayer = createAudioPlayer({ behaviors: { noSubscriber: NoSubscriberBehavior.Pause } });
    this.mediaPlayer.on('stateChange', () => this.syncSpeaking());
    this.speechPlayer.on('stateChange', () => this.syncSpeaking());
    this.mediaPlayer.on('error', (error) => {
      if (!this.media || error.resource !== this.media.resource) return;
      this.lastError = 'media_playback_failed'; this.stopMedia(this.media);
    });
    this.mediaPlayer.on(AudioPlayerStatus.Idle, (oldState) => {
      if (this.media?.resource && oldState.resource === this.media.resource) this.stopMedia(this.media);
    });
    this.speechPlayer.on('error', (error) => {
      if (this.cue && error.resource === this.cue.resource) { this.finishCue(); return; }
      if (error.resource !== this.utterance?.resource) return;
      const utterance = this.utterance;
      this.lastError = 'speech_playback_failed'; this.finishSpeech(false);
      this.queueCue('error', utterance, utterance.request_id);
    });
    this.speechPlayer.on(AudioPlayerStatus.Idle, (oldState) => {
      if (this.cue && oldState.resource === this.cue.resource) { this.finishCue(); return; }
      const utterance = this.utterance;
      if (utterance && oldState.resource === utterance.resource) {
        this.finishSpeech(utterance.ended);
        if (!utterance.ended) this.queueCue('error', utterance, utterance.request_id);
      }
    });
    this.client.on('error', () => { this.lastError = 'discord_client_error'; log('discord_client_error'); });
    this.client.on('interactionCreate', (interaction) => { void this.interaction(interaction); });
    this.client.on('messageCreate', (message) => { void this.mention(message); });
    this.client.on('voiceStateUpdate', (oldState, state) => {
      if (state.guild.id !== this.config.guild_id) return;
      if (state.id === this.client.user?.id && this.channel && state.channelId !== this.channel.id) {
        void this.leave(); // Moderator disconnect/move invalidates every identity; never follow it.
      } else if (oldState.channelId === this.channel?.id && state.channelId !== this.channel?.id) {
        if (this.pendingMedia?.announcementMemberId === state.id) this.stopMedia(this.pendingMedia);
        if (this.media?.announcementMemberId === state.id && (this.media.announcementPending || this.media.resumePending)) this.cancelMediaAnnouncement(this.media.announcementRequestId);
        if (this.wakeCalibration?.principal.member_id === state.id) this.clearWakeCalibration();
        if (this.cue?.principal?.member_id === state.id) this.finishCue(false);
        if (this.voiceRequest?.principal.member_id === state.id) { this.voiceRequest = null; this.syncSpeaking(); }
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
      generation: this.generation, receivers: this.receivers.size, voice_samples: this.samples.status(),
      active_turns: this.turns.size, pending_speech: this.pendingSpeech.size,
      playback: this.mediaPlayer.state.status, speech_playback: this.speechPlayer.state.status,
      playback_request_id: this.media?.requestId ?? null,
      playback_position_ms: this.media?.resource?.playbackDuration ?? null,
      media_paused: this.media?.paused ?? false,
      voice_cues: [...this.cueAssets.keys()], active_cue: this.cue?.name ?? null,
      voice_awake: this.voiceAwake(),
      media_handoff: this.media?.announcementPending ? 'awaiting_announcement'
        : this.media?.ready && !this.media.started ? 'ready_held' : null,
      speech_buffered_ms: this.utterance ? (this.utterance.input.readableLength + this.utterance.input.writableLength) * 20 : 0,
      // An instantaneous native value, not a cumulative underrun measurement.
      speech_player_missed_frames: this.speechPlayer.state.status === AudioPlayerStatus.Playing ? this.speechPlayer.state.missedFrames : null,
      voice_timing: this.voiceTiming ? { ...this.voiceTiming } : null,
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
    if (read.calibration) {
      if (message.request_id !== read.request_id) return;
      if (typeof message.calibration_probe_text === 'string' && message.calibration_probe_text.length <= 512) {
        read.result = { received: true, calibration_probe_text: message.calibration_probe_text };
      } else read.result = { received: true, error: 'wake_calibration_unavailable' };
      read.finish();
      return;
    }
    const result = { received: true };
    if (SPEECH_ERROR_CODES.has(message.last_error)) result.last_error = message.last_error;
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

  clearWakeCalibration() {
    const calibration = this.wakeCalibration;
    if (!calibration) return;
    this.wakeCalibration = null;
    clearTimeout(calibration.timer);
    if (calibration.principal.generation === this.generation) {
      this.sendSpeech({ type: 'reset', ...calibration.principal }, false);
    }
    if (this.diagnosticRead?.calibration === calibration) this.diagnosticRead.finish();
  }

  armWakeCalibration(memberId) {
    if (!this.channel || !this.speech || this.speech.destroyed || !this.connection
      || this.connection.state.status !== VoiceConnectionStatus.Ready) fail('speech_not_ready');
    const principal = this.principal(memberId);
    if (!SNOWFLAKE.test(memberId) || !this.currentSpeaker(principal)
      || this.channel.members.get(memberId).user.bot) fail('calibration_member_not_current');
    if (this.wakeCalibration || this.diagnosticRead || this.turns.size || this.pendingSpeech.size || this.utterance) fail('speech_busy');
    // Reset first on the same FIFO socket; ongoing receivers consult this flag
    // per packet, so no receive restart or old recognition can enter the probe.
    this.sendSpeech({ type: 'reset', ...principal });
    const calibration = { principal, expires: Date.now() + 30_000, reading: false };
    this.wakeCalibration = calibration;
    calibration.timer = setTimeout(() => {
      if (this.wakeCalibration === calibration) this.clearWakeCalibration();
    }, 30_000);
    return { wake_calibration_armed: true, member_id: memberId, expires_at_ms: calibration.expires };
  }

  async readWakeCalibration(memberId, requestId) {
    const calibration = this.wakeCalibration;
    if (!calibration || calibration.reading || calibration.principal.member_id !== memberId
      || !this.currentSpeaker(calibration.principal) || Date.now() >= calibration.expires) fail('wake_calibration_unavailable');
    if (this.diagnosticRead) fail('speech_diagnostics_busy');
    // Read results are deliberately excluded from the command replay cache.
    if (!REQUEST_ID.test(requestId ?? '') || requestId.length > 96
      || this.recent.has(requestId) || this.admissions.has(`calibration:${requestId}`)) fail('fresh_calibration_request_id_required');
    this.admissions.add(`calibration:${requestId}`);
    while (this.admissions.size > 256) this.admissions.delete(this.admissions.values().next().value);
    calibration.reading = true;
    return new Promise((resolve) => {
      const read = { socket: this.speech, generation: this.generation, calibration, request_id: requestId,
        waiting: new Map([[memberId, calibration.principal]]), result: null };
      read.finish = () => {
        if (this.diagnosticRead !== read) return;
        clearTimeout(read.timer);
        this.diagnosticRead = null;
        this.clearWakeCalibration();
        const result = read.result ?? { received: false, error: 'wake_calibration_unavailable' };
        read.result = null;
        resolve({ member_id: memberId, ...result });
      };
      this.diagnosticRead = read;
      read.timer = setTimeout(read.finish, 2000);
      if (!this.sendSpeech({ type: 'diagnostics', ...calibration.principal,
        calibration_probe: true, request_id: requestId }, false)) read.finish();
    });
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
    if (this.pendingMedia?.announcementRequestId) this.stopMedia(this.pendingMedia);
    if (this.media?.announcementRequestId && (!this.media.started || this.media.resumePending)) this.cancelMediaAnnouncement(this.media.announcementRequestId);
    this.finishCue(false);
    this.voiceRequest = null;
    this.syncSpeaking();
    this.clearWakeCalibration();
    this.speech = null;
    this.lastError = 'speech_disconnected';
    this.diagnosticRead?.finish();
    this.cancelTurns();
    for (const [id, pending] of [...this.pendingSpeech]) this.cancelRequest(id, pending, pending.source);
    for (const id of [...this.receivers.keys()]) {
      if (!this.samples.eligible(id)) this.dropReceiver(id);
    }
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
      await this.connectSpeech().catch((error) => {
        if (!this.samples.enabled || !this.samples.ready || this.samples.halted) throw error;
      });
      return this.status();
    }
    await this.leave();
    const generation = this.generation;
    await this.connectSpeech().catch((error) => {
      if (!this.samples.enabled || !this.samples.ready || this.samples.halted) throw error;
    });
    if (generation !== this.generation || this.closing) fail('join_cancelled');
    this.channel = channel;
    const connection = joinVoiceChannel({ channelId, guildId: guild.id, adapterCreator: guild.voiceAdapterCreator,
      selfDeaf: false, selfMute: false });
    this.connection = connection;
    // The public setter is also called by AudioPlayer at cue idle/unsubscribe.
    // Keep native request ownership visible through those silent playback gaps.
    const setSpeaking = connection.setSpeaking;
    connection.setSpeaking = (enabled) => setSpeaking.call(connection,
      enabled || (this.connection === connection && this.voiceAwake()));
    this.restoreSpeaking = () => { connection.setSpeaking = setSpeaking; };
    connection.on('error', () => { this.lastError = 'voice_connection_failed'; void this.leave(); });
    connection.on(VoiceConnectionStatus.Disconnected, () => { void this.leave(); });
    connection.receiver.speaking.on('start', (id) => { void this.receive(id).catch((error) => this.receiveFailed('receive', error)); });
    try { await entersState(connection, VoiceConnectionStatus.Ready, 15000); }
    catch { if (this.connection === connection) await this.leave(); fail('voice_not_ready'); }
    if (generation !== this.generation || this.connection !== connection) fail('join_cancelled');
    connection.subscribe(this.mediaPlayer);
    this.syncSpeaking();
    return this.status();
  }

  dropReceiver(id) {
    const receiver = this.receivers.get(id);
    if (!receiver) return;
    this.receivers.delete(id);
    receiver.sample?.finish();
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
      if (!this.speech || this.speech.destroyed) {
        if (this.samples.eligible(memberId)) {
          void this.connectSpeech().catch(() => { this.lastError = 'speech_disconnected'; });
        } else await this.connectSpeech();
      }
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
        if (this.wakeCalibration && Date.now() >= this.wakeCalibration.expires) this.clearWakeCalibration();
        const calibration = this.wakeCalibration;
        const calibrating = calibration && this.samePrincipal(calibration.principal, principal);
        const probe = this.voiceProbe;
        const probing = probe && probe.member_id === memberId && probe.generation === generation
          && performance.now() < probe.deadline;
        if (calibrating || probing) {
          // Exclude the complete current packet stream, including its buffered
          // tail, even if a diagnostic finishes before speaking.end.
          record.sampleExcluded = true;
          record.sample?.finish(false);
          record.sample = null;
        }
        if (calibrating && calibration.reading) return;
        if (!this.speech || this.speech.destroyed || record.blockedSpeech === this.speech) return;
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
            sample_rate: 16000, channels: 1, format: 's16le', ...(calibrating ? { calibration_probe: true } : {}) });
          this.countReceive('forwarded_pcm_bytes', pcm.length);
        } catch (error) {
          if (at === 'opus_decode' && error instanceof TypeError
            && error.message === 'The compressed data passed is corrupted') {
            // The pinned binding's OPUS_INVALID_PACKET leaves decoder state
            // intact. Drop that packet, not the subscription: speaking.start
            // will not fire again while subsequent packets keep arriving.
            this.countReceive('invalid_opus_packets');
            return;
          }
          if (at === 'speech_send' && this.samples.eligible(memberId)) {
            record.blockedSpeech = this.speech;
            this.receiveFailed(at, error);
          } else rejected(at, error);
        }
      });
      // Feed sample decoding after the existing ASR listener has forwarded PCM.
      opus.on('data', (packet) => { if (current()) this.samplePacket(record, packet, member, principal); });
      opus.on('end', () => {
        if (!current()) return;
        this.dropReceiver(memberId);
      });
    } catch (error) {
      this.receiveFailed(phase, error);
      opus?.destroy();
    }
  }

  samplePacket(record, packet, member, principal) {
    if (record.sampleExcluded || !this.samples.eligible(member.id)) return;
    try {
      if (record.sample?.closed) record.sample = null;
      if (!record.sample) {
        record.sample = this.samples.begin(member.id, member.displayName, principal.channel_id);
        if (!record.sample) return;
        record.sampleDecoder = new OpusEncoder(48000, 1);
      }
      record.sample.push(record.sampleDecoder.decode(packet));
    } catch (error) {
      if (error instanceof TypeError && error.message === 'The compressed data passed is corrupted') return;
      record.sample?.finish(false);
      record.sample = null;
      record.sampleExcluded = true;
      log('sample_decode_failed');
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
    if (this.pendingMedia?.announcementRequestId === requestId) this.stopMedia(this.pendingMedia);
    this.cancelMediaAnnouncement(requestId);
    if (this.pendingCue?.requestId === requestId) this.pendingCue = null;
    if (this.cue?.requestId === requestId) this.finishCue(false);
    if (this.voiceRequest?.requestId === requestId) { this.voiceRequest = null; this.syncSpeaking(); }
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

  stop(originRequestId = null, memberId = null, audible = true) {
    this.clearWakeCalibration();
    this.voiceProbe = null;
    if (originRequestId !== null) {
      const origin = this.turns.get(originRequestId);
      if (!REQUEST_ID.test(originRequestId) || !origin || origin.controller.signal.aborted
        || origin.principal.guild_id !== this.config.guild_id || origin.principal.member_id !== memberId) fail('stop_origin_not_current');
      // The Agent can stop current output and still return this exact turn's
      // ordinary reply. Its speech owner/request must survive that receipt.
      this.finishCue(false);
      this.cancelTurns(null, originRequestId);
      for (const [id, pending] of [...this.pendingSpeech]) this.cancelRequest(id, pending, pending.source);
      this.finishSpeech(false);
      this.stopMedia();
      if (audible) this.queueCue('cancel');
      return { ...this.status(), preserved_origin_turn: true };
    }
    this.finishCue(false);
    this.voiceRequest = null;
    this.syncSpeaking();
    this.cancelTurns();
    for (const [id, pending] of [...this.pendingSpeech]) this.cancelRequest(id, pending, pending.source);
    this.generation = randomUUID();
    this.diagnosticRead?.finish();
    this.finishSpeech(false);
    this.stopMedia();
    for (const id of [...this.receivers.keys()]) this.dropReceiver(id);
    this.sendSpeech({ type: 'reset', generation: this.generation }, false);
    if (audible) this.queueCue('cancel');
    return this.status(); // Speaking listener remains armed; next utterance uses fresh generation.
  }

  async leave() {
    this.stop(null, null, false);
    const connection = this.connection;
    this.restoreSpeaking?.();
    this.restoreSpeaking = null;
    this.connection = null;
    this.channel = null;
    this.speech?.destroy();
    this.speech = null;
    if (connection && connection.state.status !== VoiceConnectionStatus.Destroyed) connection.destroy();
    await Promise.allSettled([...this.mediaCleanups]);
    await this.samples.drain();
    return this.status();
  }

  async turn(text, principal, requestId, source, memoryWriteback = true) {
    if (typeof text !== 'string' || !text.trim() || text.length > TEXT_LIMIT) fail('invalid_text');
    if (this.turns.size) fail('agent_busy');
    if (!REQUEST_ID.test(requestId)) fail('invalid_request_id');
    this.clearWakeCalibration();
    const admission = `${source}:${requestId}`;
    if (this.admissions.has(admission)) fail('turn_already_admitted');
    this.admissions.add(admission);
    while (this.admissions.size > 256) this.admissions.delete(this.admissions.values().next().value);
    const controller = new AbortController();
    const turn = { controller, principal, source };
    this.turns.set(requestId, turn);
    // Receipt of validated speech, never a claim about an eventual Tool effect.
    if (source === 'voice' && this.currentSpeaker(principal)) this.queueCue('accepted', principal, requestId);
    const timeout = setTimeout(() => this.cancelRequest(requestId, principal, source), 120000);
    const generation = this.generation;
    try {
      const response = await fetch('http://127.0.0.1:8765/api/discord/turns', {
        method: 'POST', signal: controller.signal,
        headers: { Authorization: `Bearer ${this.ingressToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...principal, request_id: requestId, text, source, memory_writeback: memoryWriteback }),
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
      const cancelled = controller.signal.aborted;
      this.cancelRequest(requestId, principal, source);
      if (source === 'voice' && !cancelled) this.queueCue('error', principal, requestId);
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
    // Diagnostics never enters dialogue; calibration uses a read correlation ID.
    if (message.type === 'diagnostics') { this.acceptSpeechDiagnostics(message); return; }
    if (this.wakeCalibration && this.samePrincipal(this.wakeCalibration.principal, principal)
      && ['wake', 'transcript'].includes(message.type)) return;
    if (message.type === 'error') {
      if (this.wakeCalibration && this.samePrincipal(this.wakeCalibration.principal, principal)) this.clearWakeCalibration();
      if (this.currentSpeaker(principal)) this.speechWorkerError = SPEECH_ERROR_CODES.has(message.code) ? message.code : 'unclassified_speech_worker_error';
      this.lastError = 'speech_worker_error';
      const pending = this.pendingSpeech.get(message.request_id);
      const turn = this.turns.get(message.request_id);
      if (!this.cancelledRequests.has(message.request_id) && ((pending && this.samePrincipal(pending, principal))
        || (turn && this.samePrincipal(turn.principal, principal))
        || (this.voiceRequest?.requestId === message.request_id && this.samePrincipal(this.voiceRequest.principal, principal)))) {
        this.cancelRequest(message.request_id, principal, 'voice');
        this.queueCue('error', principal, message.request_id);
      }
      return;
    }
    if (!REQUEST_ID.test(message.request_id ?? '')) return;
    if (this.cancelledRequests.has(message.request_id)) return;
    if (message.type === 'wake') {
      if (!this.currentSpeaker(principal)) return;
      this.clearWakeCalibration(); this.countReceive('wake_events');
      const previousRequestId = this.voiceRequest?.requestId;
      this.voiceRequest = { requestId: message.request_id, principal };
      this.syncSpeaking();
      this.queueCue(message.cue_name === 'follow_up' ? 'follow_up' : 'ready', principal, message.request_id);
      if (message.cue_name === 'follow_up') this.releaseMediaAnnouncement(previousRequestId);
      return;
    }
    if (message.type === 'cue') {
      if (this.voiceRequest?.requestId === message.request_id && this.samePrincipal(this.voiceRequest.principal, principal)
        && ['complete', 'cancel'].includes(message.name)) {
        this.queueCue(message.name, principal, message.request_id);
        this.voiceRequest = null;
        this.syncSpeaking();
        if (message.name === 'complete') this.releaseMediaAnnouncement(message.request_id);
      }
      return;
    }
    if (message.type === 'transcript') {
      if (this.admissions.has(`voice:${message.request_id}`)) return;
      const member = this.channel.members.get(message.member_id);
      if (!member || member.user.bot || member.voice.channelId !== this.channel.id) return;
      this.countReceive('transcript_events');
      const probe = this.voiceProbe;
      const diagnostic = probe && probe.member_id === message.member_id
        && probe.generation === this.generation && performance.now() < probe.deadline;
      if (diagnostic) this.voiceProbe = null; // One exact member turn only.
      const timing = { request_id: message.request_id, diagnostic: !!diagnostic,
        transcript_monotonic_ms: Number(process.hrtime.bigint()) / 1e6 };
      this.voiceTiming = timing;
      try {
        const result = await this.turn(message.text, principal, message.request_id, 'voice', !diagnostic);
        timing.agent_ms = Math.round(Number(process.hrtime.bigint()) / 1e6 - timing.transcript_monotonic_ms);
        timing.run_id = result.run_id ?? null;
        if (result.status !== 'completed') {
          this.cancelRequest(message.request_id, principal, 'voice');
          this.queueCue(result.status === 'interrupted' ? 'cancel' : 'error', principal, message.request_id); return;
        }
        if (!result.reply.trim()) {
          // Successful silent completion still releases its prepared track after
          // the completion cue. Failure/cancellation never leaves latent music.
          this.sendSpeech({ type: 'cancel', ...principal, request_id: message.request_id }, false);
          if (this.voiceRequest?.requestId === message.request_id) { this.voiceRequest = null; this.syncSpeaking(); }
          this.queueCue('complete', principal, message.request_id);
          this.releaseMediaAnnouncement(message.request_id); return;
        }
        const memberNow = this.channel?.members.get(message.member_id);
        if (!memberNow || memberNow.voice.channelId !== principal.channel_id || !this.samePrincipal(principal, this.principal(message.member_id))) fail('speaker_not_current');
        this.requestSpeech(principal, message.request_id, result.reply, 'voice');
      } catch {
        const cancelled = this.cancelledRequests.has(message.request_id);
        this.cancelRequest(message.request_id, principal, 'voice'); this.lastError = 'voice_turn_failed';
        if (!cancelled) this.queueCue('error', principal, message.request_id);
      }
    } else if (message.type === 'speech_audio') {
      const pending = this.pendingSpeech.get(message.request_id);
      if (!pending || !this.samePrincipal(pending, principal) || !this.currentSpeaker(principal)) return;
      if (message.sample_rate !== 24000 || message.channels !== 1 || message.format !== 's16le' || typeof message.pcm !== 'string' || message.pcm.length > 60000
        || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(message.pcm)) fail('invalid_speech_audio');
      if (!this.utterance) {
        if (this.voiceTiming?.request_id === message.request_id) this.voiceTiming.first_pcm_ms =
          Math.round(Number(process.hrtime.bigint()) / 1e6 - this.voiceTiming.transcript_monotonic_ms);
        this.startSpeech(principal, message.request_id);
      }
      const utterance = this.utterance;
      if (utterance.request_id !== message.request_id || utterance.member_id !== message.member_id) return;
      const pcm = Buffer.from(message.pcm, 'base64');
      if (!pcm.length || pcm.length % 2) fail('invalid_speech_audio');
      this.writeSpeech(pcm);
    } else if (message.type === 'speech_end') {
      const pending = this.pendingSpeech.get(message.request_id);
      if (!pending || !this.samePrincipal(pending, principal) || !this.currentSpeaker(principal)) return;
      if (this.utterance?.request_id === message.request_id && this.samePrincipal(this.utterance, principal)) this.writeSpeech(Buffer.alloc(0), true);
      else this.cancelRequest(message.request_id, pending, pending.source);
    }
  }

  voiceAwake() {
    return !!this.voiceRequest && this.currentSpeaker(this.voiceRequest.principal);
  }

  syncSpeaking() {
    const connection = this.connection;
    if (!connection || connection.state.status !== VoiceConnectionStatus.Ready) return;
    const player = connection.state.subscription?.player;
    // Real cue/reply/media packets keep their ordinary speaking signal. A native
    // awake request additionally holds it without generating any extra audio.
    connection.setSpeaking(player?.state.status === AudioPlayerStatus.Playing);
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
    this.clearWakeCalibration();
    this.pendingSpeech.set(requestId, { ...principal, source });
    this.speechDeadlines.set(requestId, setTimeout(() => this.cancelRequest(requestId, principal, source), 120000));
    try { this.sendSpeech({ type: 'speak', ...principal, source: source === 'owner' ? 'owner' : undefined, request_id: requestId, text }); }
    catch (error) { this.cancelRequest(requestId, principal, source); throw error; }
  }

  queueCue(name, principal = null, requestId = null) {
    if (!this.cueAssets.has(name) || !this.connection || this.closing || this.utterance || this.pendingSpeech.size
      || (principal && !this.currentSpeaker(principal))) return;
    const cue = { name, principal, requestId, generation: this.generation, expires: performance.now() + 1500 };
    if (this.cue) {
      // One latest pending cue, never a backlog of obsolete acknowledgements.
      if (this.cue.name !== name || this.cue.requestId !== requestId) this.pendingCue = cue;
      return;
    }
    this.startCue(cue);
  }

  startCue(cue) {
    if (performance.now() >= cue.expires || cue.generation !== this.generation || !this.connection
      || this.closing || this.utterance || this.pendingSpeech.size
      || (cue.principal && !this.currentSpeaker(cue.principal))) return;
    const packets = this.cueAssets.get(cue.name);
    if (!packets) return;
    cue.media = this.media;
    cue.connection = this.connection;
    cue.resumeMedia = !!this.media && this.mediaPlayer.state.status === AudioPlayerStatus.Playing;
    cue.input = Readable.from(packets, { objectMode: true });
    cue.resource = createAudioResource(cue.input, { inputType: StreamType.Opus });
    this.cue = cue;
    cue.input.on('error', () => { if (this.cue === cue) this.finishCue(); });
    // Bound a stalled/disconnected player as well as the normal finite clip.
    cue.timer = setTimeout(() => { if (this.cue === cue) this.finishCue(); }, packets.length * 20 + 1000);
    try {
      this.mediaPlayer.pause();
      this.connection.subscribe(this.speechPlayer);
      this.speechPlayer.play(cue.resource);
    } catch { this.finishCue(false); } // Optional feedback must never reject a voice turn.
  }

  finishCue(next = true) {
    const cue = this.cue;
    const pending = next ? this.pendingCue : null;
    this.cue = this.pendingCue = null;
    if (cue) {
      clearTimeout(cue.timer);
      this.speechPlayer.stop(true);
      cue.input.destroy();
      if (cue.generation === this.generation && this.connection === cue.connection) {
        try { this.connection.subscribe(this.mediaPlayer); } catch { /* Connection teardown owns recovery. */ }
        if (cue.resumeMedia && this.media === cue.media && this.media?.generation === this.generation
          && !this.media.announcementPending && !this.media.paused) this.mediaPlayer.unpause();
      }
    }
    if (pending) this.startCue(pending);
    this.maybeStartMedia();
  }

  startSpeech(principal, requestId) {
    if (!this.connection || this.utterance) fail('voice_not_ready_or_speaking');
    this.finishCue(false); // Speech owns the player from the first PCM; stale cues never delay it.
    // Opus accepts native 24k mono; Discord's player supplies the 20 ms wire
    // clock. Avoid FFmpeg's byte-stream buffering and a second Opus encoder.
    const encoder = new OpusEncoder(24000, 1);
    const input = new PassThrough({ objectMode: true, highWaterMark: TTS_MAX_BUFFER_FRAMES });
    const utterance = { ...principal, source: this.pendingSpeech.get(requestId)?.source, request_id: requestId,
      input, encoder, remainder: Buffer.alloc(0), started: false, ended: false,
      media: this.media, resumeMedia: !!this.media && this.mediaPlayer.state.status === AudioPlayerStatus.Playing };
    this.utterance = utterance;
    input.on('error', () => { if (this.utterance === utterance) this.finishSpeech(false); });
  }

  writeSpeech(pcm, end = false) {
    const utterance = this.utterance;
    if (!utterance || utterance.ended) fail('speech_not_current');
    const enqueue = (frame) => {
      if (utterance.input.readableLength + utterance.input.writableLength >= TTS_MAX_BUFFER_FRAMES) fail('speech_audio_backpressure');
      const boosted = Buffer.allocUnsafe(frame.length);
      const headroom = TTS_PEAK_CEILING - TTS_PEAK_KNEE;
      for (let at = 0; at < frame.length; at += 2) {
        const value = frame.readInt16LE(at) / 32768 * TTS_GAIN;
        const magnitude = Math.abs(value);
        const protectedValue = magnitude > TTS_PEAK_KNEE
          ? Math.sign(value) * (TTS_PEAK_KNEE + headroom * Math.tanh((magnitude - TTS_PEAK_KNEE) / headroom))
          : value;
        boosted.writeInt16LE(Math.round(protectedValue * 32767), at);
      }
      utterance.input.write(utterance.encoder.encode(boosted));
    };
    const data = Buffer.concat([utterance.remainder, pcm]);
    let offset = 0;
    for (; offset + TTS_FRAME_BYTES <= data.length; offset += TTS_FRAME_BYTES) {
      enqueue(data.subarray(offset, offset + TTS_FRAME_BYTES));
    }
    // Copy only the sub-frame remainder, never retain the larger input buffer.
    utterance.remainder = Buffer.from(data.subarray(offset));
    if (end) {
      if (utterance.remainder.length) {
        const frame = Buffer.alloc(TTS_FRAME_BYTES);
        utterance.remainder.copy(frame);
        enqueue(frame);
        utterance.remainder = Buffer.alloc(0);
      }
      // Drain the codec's lookahead so the final speech samples are preserved.
      enqueue(Buffer.alloc(TTS_FRAME_BYTES));
      utterance.ended = true;
      utterance.encoder = null;
    }
    if (!utterance.started && (utterance.input.readableLength >= TTS_PREBUFFER_FRAMES || end)) {
      utterance.started = true;
      this.mediaPlayer.pause();
      this.connection.subscribe(this.speechPlayer);
      utterance.resource = createAudioResource(utterance.input, { inputType: StreamType.Opus });
      this.speechPlayer.play(utterance.resource);
      if (this.voiceTiming?.request_id === utterance.request_id) this.voiceTiming.playback_ms =
        Math.round(Number(process.hrtime.bigint()) / 1e6 - this.voiceTiming.transcript_monotonic_ms);
    }
    if (end) utterance.input.end();
  }

  finishSpeech(played) {
    const utterance = this.utterance;
    if (!utterance) return;
    this.utterance = null;
    this.speechPlayer.stop(true);
    utterance.input.destroy();
    utterance.encoder = null;
    utterance.remainder = Buffer.alloc(0);
    if (utterance.generation === this.generation) {
      this.pendingSpeech.delete(utterance.request_id);
      clearTimeout(this.speechDeadlines.get(utterance.request_id));
      this.speechDeadlines.delete(utterance.request_id);
      if (!played) this.cancelRequest(utterance.request_id, utterance, utterance.source);
      else this.sendSpeech({ type: 'played', generation: utterance.generation,
        guild_id: utterance.guild_id, channel_id: utterance.channel_id, member_id: utterance.member_id,
        request_id: utterance.request_id }, false);
      if (this.connection) this.connection.subscribe(this.mediaPlayer);
      if (utterance.resumeMedia && this.media === utterance.media && this.media?.generation === this.generation
        && !this.media.announcementPending && !this.media.paused) this.mediaPlayer.unpause();
      this.maybeStartMedia();
    }
  }

  cancelMediaAnnouncement(requestId) {
    const media = this.media;
    if (!media || media.announcementRequestId !== requestId) return;
    if (media.started && media.resumePending) {
      // Cancelling a resume keeps the exact paused stream and position.
      media.paused = true;
      media.resumePending = media.announcementPending = false;
      media.announcementRequestId = media.announcementMemberId = null;
      this.mediaPlayer.pause();
    } else this.stopMedia(media);
  }

  releaseMediaAnnouncement(requestId) {
    const media = this.media;
    if (!requestId || !media || media.announcementRequestId !== requestId) return;
    media.announcementPending = false;
    this.maybeStartMedia();
  }

  maybeStartMedia() {
    const media = this.media;
    if (!media?.ready || (media.started && !media.resumePending) || media.announcementPending || media.paused
      || this.cue || this.pendingCue || this.utterance || this.pendingSpeech.size
      || media.generation !== this.generation || this.closing
      || this.connection?.state.status !== VoiceConnectionStatus.Ready) return;
    try {
      this.connection.subscribe(this.mediaPlayer);
      if (media.started) this.mediaPlayer.unpause();
      else { media.started = true; this.mediaPlayer.play(media.resource); }
      media.resumePending = false;
    } catch { this.lastError = 'media_playback_failed'; this.stopMedia(media); }
  }

  stopMedia(expected = null) {
    if (!expected) {
      if (this.pendingMedia) this.stopMedia(this.pendingMedia);
      if (this.media) this.stopMedia(this.media);
      return;
    }
    const active = this.media === expected;
    if (!active && this.pendingMedia !== expected) return;
    const media = expected;
    if (this.pendingMedia === media) this.pendingMedia = null;
    if (active) this.media = null;
    clearTimeout(media.startTimer);
    media.startAbort.abort();
    if (active) this.mediaPlayer.stop(true);
    media.resource?.playStream.destroy();
    for (const child of media.children) {
      child.stdout?.unpipe();
      child.stdin?.destroy();
      child.stdout?.destroy();
      // The extractor may spawn a JavaScript runtime; its whole owned group
      // must stop even when its leader has already closed its output.
      try { process.kill(-child.pid, 'SIGKILL'); } catch {}
    }
    if (media.handle) media.cleanup.push(media.handle.close().catch(() => {}));
    const cleanup = Promise.allSettled(media.cleanup).then(async () => {
      // Reap the downloader before removing its fragment workspace. Admission
      // is included above, so a cancellation during mkdtemp cannot orphan it.
      if (media.directory) await fs.rm(media.directory, { recursive: true, force: true }).catch(() => {});
    });
    this.mediaCleanups.add(cleanup);
    void cleanup.finally(() => this.mediaCleanups.delete(cleanup));
  }

  cancelMedia(requestId) {
    if (!REQUEST_ID.test(requestId ?? '')) fail('playback_request_id_required');
    this.cancelledMediaRequests.add(requestId);
    while (this.cancelledMediaRequests.size > 256) this.cancelledMediaRequests.delete(this.cancelledMediaRequests.values().next().value);
    const active = this.media?.requestId === requestId ? this.media : null;
    const pending = this.pendingMedia?.requestId === requestId ? this.pendingMedia : null;
    const stopped = !!active || !!pending;
    if (active) this.stopMedia(active);
    if (pending) this.stopMedia(pending);
    return { playback_request_id: requestId, playback_stopped: stopped,
      delivery: stopped ? 'audio_playback_stopped' : 'media_cancellation_registered', ...this.status() };
  }

  async play(message) {
    if (!this.connection || !this.channel || this.connection.state.status !== VoiceConnectionStatus.Ready) fail('voice_not_ready');
    if (this.utterance || this.pendingSpeech.size) fail('speech_busy');
    if (this.pendingMedia) fail('media_start_busy');
    const { path: filename, file_identity: identity, source, expires_at_ms: expiresAt, request_id: requestId } = message;
    const streamed = source !== undefined;
    const torbox = source?.provider === 'torbox_web';
    const soundcloud = source?.provider === 'soundcloud';
    if (streamed) {
      if (!source || typeof source !== 'object' || Array.isArray(source)
        || Object.keys(source).length !== (torbox ? 3 : 2)
        || !['youtube', 'torbox_web', 'soundcloud'].includes(source.provider)
        || (soundcloud ? typeof source.track_id !== 'string' || !/^[0-9]{1,20}$/.test(source.track_id)
          : typeof source.video_id !== 'string' || !/^[A-Za-z0-9_-]{11}$/.test(source.video_id))
        || Object.hasOwn(message, 'path') || Object.hasOwn(message, 'file_identity')) fail('invalid_media_source');
      if (torbox) {
        if (typeof source.url !== 'string' || source.url.length > 8192
          || /[\x00-\x20\x7f-\x9f]/.test(source.url) || source.url.includes('#')) fail('invalid_media_source');
        let url;
        try { url = new URL(source.url); } catch { fail('invalid_media_source'); }
        if (url.protocol !== 'https:' || url.username || url.password || url.hash || url.port
          || !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+torbox\.app$/.test(url.hostname)
          || url.href !== source.url) fail('invalid_media_source');
      }
    } else {
      const identityFields = ['dev', 'ino', 'size', 'mtime_ns'];
      if (!identity || typeof identity !== 'object' || Array.isArray(identity)
        || Object.keys(identity).length !== identityFields.length
        || identityFields.some((key) => typeof identity[key] !== 'string' || !/^[0-9]{1,30}$/.test(identity[key]))) fail('media_file_identity_required');
      if (typeof filename !== 'string' || !/^\/proc\/\d+\/fd\/\d+$/.test(filename)) fail('admitted_media_descriptor_required');
    }
    if (!Number.isSafeInteger(expiresAt) || expiresAt > Date.now() + 15000) fail('invalid_media_deadline');
    const generation = this.generation;
    const channel = this.channel;
    const connection = this.connection;
    const current = () => generation === this.generation && channel === this.channel && connection === this.connection
      && connection.state.status === VoiceConnectionStatus.Ready && !this.closing
      && !this.cancelledMediaRequests.has(requestId) && Date.now() < expiresAt
      && (!message.member_id || this.currentSpeaker({ generation, guild_id: this.config.guild_id,
        channel_id: channel.id, member_id: message.member_id }));
    if (!current()) fail('media_request_expired_or_cancelled');
    // There is one admitted turn; bind only the exact invoking voice member.
    const origin = [...this.turns].find(([, turn]) => turn.source === 'voice'
      && message.member_id === turn.principal.member_id && this.currentSpeaker(turn.principal));
    const media = { generation, requestId, children: [], cleanup: [], startAbort: new AbortController(),
      announcementRequestId: origin?.[0] ?? null, announcementMemberId: origin?.[1].principal.member_id ?? null,
      announcementPending: !!origin, ready: false, started: false, paused: false };
    this.pendingMedia = media;
    media.startTimer = setTimeout(() => this.stopMedia(media), Math.max(1, expiresAt - Date.now()));
    const ownedChild = (executable, args, options) => {
      const child = spawn(executable, args, { ...options, detached: true });
      media.children.push(child);
      media.cleanup.push(new Promise((resolve) => child.once('close', resolve)));
      child.on('error', () => this.stopMedia(media));
      child.stdin?.on('error', () => this.stopMedia(media));
      child.stdout?.on('error', () => this.stopMedia(media));
      child.on('close', (code) => { if (code) this.stopMedia(media); });
      return child;
    };
    try {
      if (streamed) {
        const admission = fs.mkdtemp(join(tmpdir(), 'obsidience-music-')).then((directory) => { media.directory = directory; });
        media.cleanup.push(admission.catch(() => {}));
        await admission;
      } else {
        // Verify a replacement while the previous item remains owned/playing.
        const admission = (async () => {
          const handle = await fs.open(filename, 'r');
          if (this.pendingMedia !== media || !current()) { await handle.close(); fail('play_cancelled'); }
          media.handle = handle;
          const stat = await handle.stat({ bigint: true });
          if (!stat.isFile() || stat.dev.toString() !== identity.dev || stat.ino.toString() !== identity.ino
            || stat.size.toString() !== identity.size || stat.mtimeNs.toString() !== identity.mtime_ns) fail('admitted_media_identity_changed');
        })();
        media.cleanup.push(admission.catch(() => {}));
        await admission;
      }
      if (this.pendingMedia !== media || this.utterance || this.pendingSpeech.size || !current()) fail('play_cancelled');
      if (!media.announcementRequestId) this.finishCue(false);
      if (this.media) this.stopMedia(this.media);
      this.pendingMedia = null;
      this.media = media;
      const child = ownedChild('/usr/bin/ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1', '-filter_threads', '1',
        '-protocol_whitelist', streamed ? 'pipe' : 'file,pipe', '-i', streamed ? 'pipe:0' : '/proc/self/fd/3',
        '-vn', '-af', 'volume=-4dB,afade=t=in:st=0:d=0.4', '-f', 's16le', '-ar', '48000', '-ac', '2', 'pipe:1'],
      { stdio: streamed ? ['pipe', 'pipe', 'ignore'] : ['ignore', 'pipe', 'ignore', media.handle.fd], env: { PATH: '/usr/bin', LANG: 'C' } });
      if (streamed) {
        const runtime = fileURLToPath(new URL('../', import.meta.url));
        const provider = ownedChild(fileURLToPath(new URL('../../.venv/bin/python', import.meta.url)),
          torbox ? ['-m', 'harness.media.web_music', 'stream']
            : ['-m', 'harness.media.online_music', 'stream', source.provider, soundcloud ? source.track_id : source.video_id],
          { cwd: media.directory, stdio: [torbox ? 'pipe' : 'ignore', 'pipe', 'ignore'], env: { PATH: '/usr/bin', LANG: 'C', PYTHONPATH: runtime } });
        // The private CDN URL never enters argv, environment or logs.
        if (torbox) provider.stdin.end(JSON.stringify({ url: source.url }));
        // Native pipe backpressure bounds both the compressed and decoded queues.
        provider.stdout.pipe(child.stdin);
      }
      media.resource = createAudioResource(child.stdout, { inputType: StreamType.Raw });
      // prism-media exposes a supported encoder control capped at 128 kbps.
      const bitrate = Number.isSafeInteger(channel.bitrate) ? Math.max(16000, Math.min(128000, channel.bitrate)) : null;
      if (bitrate !== null) media.resource.encoder?.setBitrate(bitrate);
      if (media.announcementRequestId) {
        // Readiness means a real decoded/encoded packet exists. Do not play it
        // while the Agent is still forming the announcement after this receipt.
        await new Promise((resolve, reject) => {
          const stream = media.resource.playStream;
          const done = (error) => {
            stream.off('readable', readable); stream.off('end', closed);
            stream.off('close', closed); stream.off('error', closed);
            media.startAbort.signal.removeEventListener('abort', closed);
            error ? reject(new Error('audio_playback_not_ready')) : resolve();
          };
          const readable = () => { if (stream.readableLength) done(); else if (stream.readableEnded) done(true); };
          const closed = () => done(true);
          stream.on('readable', readable); stream.once('end', closed);
          stream.once('close', closed); stream.once('error', closed);
          media.startAbort.signal.addEventListener('abort', closed, { once: true });
          if (media.startAbort.signal.aborted || stream.destroyed) done(true);
          else readable();
        });
        if (this.media !== media || !current()) fail('play_cancelled');
        media.ready = true;
      } else {
        media.ready = media.started = true;
        connection.subscribe(this.mediaPlayer);
        this.mediaPlayer.play(media.resource);
        try { await entersState(this.mediaPlayer, AudioPlayerStatus.Playing, media.startAbort.signal); }
        catch { fail('audio_playback_not_started'); }
        if (this.media !== media || !current()) fail('play_cancelled');
      }
      clearTimeout(media.startTimer);
      return { delivery: media.announcementPending ? 'audio_playback_ready' : 'audio_playback_started',
        awaiting_announcement: media.announcementPending,
        playback_request_id: requestId, media_kind: 'audio_only', video_supported: false,
        ...(streamed ? { provider: source.provider, audio_bitrate: bitrate ?? null } : {}), ...this.status() };
    } catch (error) {
      this.stopMedia(media);
      throw error;
    }
  }

  async command(message) {
    const readOnly = ['status', 'channels', 'speech_diagnostics', 'read_wake_calibration'].includes(message.command)
      || (message.command === 'samples' && (message.action ?? 'status') === 'status');
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
      if (message.member_id !== undefined && !['cancel_media', 'wake_calibration', 'read_wake_calibration'].includes(message.command)) {
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
        case 'samples':
          if (Object.keys(message).some((key) => !['command', 'request_id', 'guild_id', 'member_id', 'action'].includes(key))) fail('invalid_samples_request');
          value = { voice_samples: await this.samples.control(message.action ?? 'status', message.member_id) };
          break;
        case 'channels': value = { channels: await this.channels() }; break;
        case 'voice_probe':
          if (Object.keys(message).some((key) => !['command', 'request_id', 'member_id'].includes(key))) fail('owner_probe_only');
          if (!SNOWFLAKE.test(message.member_id ?? '') || !this.currentSpeaker(this.principal(message.member_id))) fail('probe_member_not_current');
          if (this.turns.size || this.pendingSpeech.size || this.utterance) fail('speech_busy');
          this.voiceProbe = { member_id: message.member_id, generation: this.generation, deadline: performance.now() + 30000 };
          value = { armed: true, expires_in_seconds: 30, memory_writeback: false }; break;
        case 'speech_diagnostics':
          if (Object.keys(message).some((key) => !['command', 'request_id'].includes(key))) fail('owner_diagnostics_only');
          value = await this.speechDiagnostics(); break;
        case 'wake_calibration':
        case 'read_wake_calibration':
          if (Object.keys(message).some((key) => !['command', 'request_id', 'member_id'].includes(key))) fail('owner_calibration_only');
          value = message.command === 'wake_calibration' ? this.armWakeCalibration(message.member_id)
            : await this.readWakeCalibration(message.member_id, message.request_id);
          break;
        case 'join': value = await this.join(message.channel_id); break;
        case 'leave': value = await this.leave(); break;
        case 'stop': value = this.stop(message.origin_request_id ?? null, message.member_id ?? null); break;
        case 'pause':
          if (this.media) this.media.paused = true;
          if (this.utterance) this.utterance.resumeMedia = false;
          if (this.cue) this.cue.resumeMedia = false;
          value = { paused: this.mediaPlayer.pause() || !!this.media?.paused, ...this.status() }; break;
        case 'resume':
          if (!this.media?.ready) fail('no_media_to_resume');
          this.media.paused = false;
          this.media.resumePending = true;
          {
            const origin = [...this.turns].find(([, turn]) => turn.source === 'voice'
              && message.member_id === turn.principal.member_id && this.currentSpeaker(turn.principal));
            if (origin) {
              this.media.announcementRequestId = origin[0];
              this.media.announcementMemberId = origin[1].principal.member_id;
              this.media.announcementPending = true;
              this.mediaPlayer.pause();
            }
          }
          this.maybeStartMedia();
          value = { resumed: this.mediaPlayer.state.status === AudioPlayerStatus.Playing,
            resume_pending: this.media.resumePending, ...this.status() };
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
    if (!['join', 'leave', 'status', 'ask', 'stop', 'samples'].includes(name)) return;
    try {
      await interaction.deferReply({ flags: MessageFlags.Ephemeral });
      const guild = await this.guild();
      const member = await guild.members.fetch(interaction.user.id);
      const manager = member.permissions.has(PermissionFlagsBits.ManageGuild);
      if (name === 'samples') {
        const action = interaction.options.getString('action', true);
        const result = await this.samples.control(action, member.id);
        let content;
        if (action === 'delete') content = 'Your saved voice samples were deleted. Recording is paused for you. Use /samples action:start to opt back in.';
        else if (action === 'stop') content = 'Your voice sampling is paused. Your existing samples are kept.';
        else {
          const state = !result.enabled ? 'Voice sampling is disabled.'
            : !result.ready || result.halted ? 'Voice sampling is currently paused. Your existing samples are kept.'
              : result.opted_out ? 'Your voice sampling is paused.'
                : result.member_quota_reached ? 'Your sample storage limit has been reached. Recording is paused for you.'
                  : 'Your voice sampling is enabled while you share Bard’s voice channel.';
          content = `${state} Saved samples: ${(result.member_stored_bytes / (1024 * 1024)).toFixed(1)} MiB. Use /samples action:stop to pause or action:delete to remove your samples.`;
        }
        await interaction.editReply({ content, allowedMentions: ALLOWED_MENTIONS });
        return;
      }
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
      if (interaction.deferred) await interaction.editReply({ content: 'The request could not be completed. Check bot status or your channel permissions.', allowedMentions: ALLOWED_MENTIONS }).catch(() => {});
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
    this.startupPhase = 'sample_storage';
    await this.samples.initialize();
    this.startupPhase = 'voice_cues';
    this.cueAssets = await loadCueAssets();
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
    commands.push(new SlashCommandBuilder().setName('samples').setDescription('Manage your own voice samples')
      .addStringOption((option) => option.setName('action').setDescription('Your recordings only; delete also stops capture')
        .setRequired(true).addChoices(...['status', 'stop', 'start', 'delete'].map((value) => ({ name: value, value })))));
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

import fs from 'node:fs/promises';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
const SNOWFLAKE = /^\d{17,20}$/;

const RATE = 48000;
const MAX_QUEUED_BYTES = 16 * 1024 * 1024;
const MAX_QUEUED_CHUNKS = 32;
const MAX_PREFERENCES = 10000;
const MAX_INVENTORY_ENTRIES = 1000000;
const fail = (code) => { throw new Error(code); };
const defaultDirectory = () => join(homedir(), '.local/state/obsidience-discord-samples');

export function sampleConfig(value) {
  if (value === undefined) return Object.freeze({ enabled: false });
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).some((key) => !['enabled', 'all_members', 'consent_provenance',
      'consent_attested_at', 'output_directory', 'chunk_seconds', 'max_total_bytes', 'max_member_bytes'].includes(key))) fail('invalid_sample_config');
  if (typeof value.enabled !== 'boolean') fail('invalid_sample_enabled');
  if (value.all_members !== undefined && typeof value.all_members !== 'boolean') fail('invalid_sample_consent');
  if (value.enabled && (value.all_members !== true || typeof value.consent_provenance !== 'string'
    || !value.consent_provenance.trim() || value.consent_provenance.length > 1000
    || typeof value.consent_attested_at !== 'string' || !Number.isFinite(Date.parse(value.consent_attested_at)))) fail('sample_consent_attestation_required');
  const directory = value.output_directory ?? process.env.STATE_DIRECTORY ?? defaultDirectory();
  if (typeof directory !== 'string' || !directory.startsWith('/') || resolve(directory) !== directory) fail('invalid_sample_directory');
  const limits = { chunk_seconds: value.chunk_seconds ?? 20,
    max_total_bytes: value.max_total_bytes ?? 20 * 1024 ** 3,
    max_member_bytes: value.max_member_bytes ?? 2 * 1024 ** 3 };
  if (!Number.isSafeInteger(limits.chunk_seconds) || limits.chunk_seconds < 2 || limits.chunk_seconds > 30
    || !Number.isSafeInteger(limits.max_member_bytes) || limits.max_member_bytes < 1024 * 1024
    || !Number.isSafeInteger(limits.max_total_bytes) || limits.max_total_bytes < limits.max_member_bytes
    || limits.max_total_bytes > 1024 ** 4) fail('invalid_sample_limits');
  return Object.freeze({ ...value, ...limits, output_directory: directory });
}

async function privateDirectory(directory) {
  await fs.mkdir(directory, { mode: 0o700, recursive: true });
  const stat = await fs.lstat(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid()) fail('sample_directory_not_owned');
  await fs.chmod(directory, 0o700);
}

function wavHeader(bytes) {
  const header = Buffer.alloc(44);
  header.write('RIFF'); header.writeUInt32LE(bytes + 36, 4); header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22);
  header.writeUInt32LE(RATE, 24); header.writeUInt32LE(RATE * 2, 28);
  header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34);
  header.write('data', 36); header.writeUInt32LE(bytes, 40);
  return header;
}

// This store owns local original recordings only. It never invokes a model or a
// Knowledge/Memory writer. Its one async write lane is bounded independently of ASR.
export class VoiceSamples {
  constructor(config, guildId, onEvent = () => {}) {
    this.config = config;
    this.guildId = guildId;
    this.onEvent = onEvent;
    this.enabled = config?.enabled === true;
    this.ready = false;
    this.halted = null;
    this.totalBytes = 0;
    this.memberBytes = new Map();
    this.optedOut = new Set();
    this.active = new Set();
    this.queue = Promise.resolve();
    this.controls = Promise.resolve();
    this.queuedBytes = 0;
    this.queuedChunks = 0;
    this.savedChunks = 0;
    this.droppedChunks = 0;
    this.quotaMembers = new Set();
  }

  status(memberId = null) {
    return { enabled: this.enabled, ready: this.ready, halted: this.halted,
      active_recordings: this.active.size, queued_chunks: this.queuedChunks,
      queued_bytes: this.queuedBytes, stored_bytes: this.totalBytes, saved_chunks: this.savedChunks,
      dropped_chunks: this.droppedChunks, sample_rate: RATE,
      max_total_bytes: this.config?.max_total_bytes ?? null,
      ...(memberId ? { member_id: memberId, opted_out: this.optedOut.has(memberId),
        member_stored_bytes: this.memberBytes.get(memberId) ?? 0,
        member_quota_reached: this.quotaMembers.has(memberId), max_member_bytes: this.config?.max_member_bytes ?? null } : {}) };
  }

  halt(code) {
    if (!this.halted) { this.halted = code; this.onEvent(code); }
    for (const session of [...this.active]) session.finish(false);
  }

  async initialize() {
    if (!this.enabled) return;
    try {
      // StateDirectory supplies the sole persistent writable root in the unit.
      // A custom installation must update that precise sandbox path as well.
      if (process.env.STATE_DIRECTORY && resolve(process.env.STATE_DIRECTORY) !== this.config.output_directory) fail('sample_state_directory_mismatch');
      this.root = this.config.output_directory;
      this.directory = join(this.root, this.guildId);
      await privateDirectory(this.root);
      await privateDirectory(this.directory);
      this.preferencesPath = join(this.directory, 'preferences.json');
      const preferences = await fs.lstat(this.preferencesPath).catch((error) => { if (error.code !== 'ENOENT') throw error; return null; });
      if (preferences) {
        if (!preferences.isFile() || preferences.uid !== process.getuid() || (preferences.mode & 0o077) || preferences.size > 1024 * 1024) fail('sample_preferences_invalid');
        const value = JSON.parse(await fs.readFile(this.preferencesPath, 'utf8'));
        if (!Array.isArray(value.opted_out) || value.opted_out.length > MAX_PREFERENCES
          || value.opted_out.some((id) => !SNOWFLAKE.test(id))) fail('sample_preferences_invalid');
        this.optedOut = new Set(value.opted_out);
      }
      // Count existing originals before admission, including incomplete pairs.
      // Never delete or overwrite recordings to make room.
      let entries = 0;
      for await (const entry of await fs.opendir(this.directory)) {
        if (++entries > MAX_INVENTORY_ENTRIES) fail('sample_inventory_invalid');
        if (entry.name === 'preferences.json') continue;
        if (!SNOWFLAKE.test(entry.name) || !entry.isDirectory()) fail('sample_inventory_invalid');
        const directory = join(this.directory, entry.name);
        await privateDirectory(directory);
        let bytes = 0;
        for await (const file of await fs.opendir(directory)) {
          if (++entries > MAX_INVENTORY_ENTRIES) fail('sample_inventory_invalid');
          const stat = await fs.lstat(join(directory, file.name));
          if (!stat.isFile() || stat.uid !== process.getuid() || (stat.mode & 0o077)) fail('sample_inventory_invalid');
          bytes += stat.size;
        }
        this.memberBytes.set(entry.name, bytes);
        this.totalBytes += bytes;
        if (bytes >= this.config.max_member_bytes) this.quotaMembers.add(entry.name);
      }
      this.ready = true;
      if (this.totalBytes >= this.config.max_total_bytes) this.halt('sample_total_quota_reached');
    } catch { this.halt('sample_storage_unavailable'); }
  }

  eligible(memberId) {
    return this.enabled && this.ready && !this.halted && SNOWFLAKE.test(memberId)
      && !this.optedOut.has(memberId) && !this.quotaMembers.has(memberId);
  }

  begin(memberId, displayName, channelId) {
    if (!this.eligible(memberId) || !SNOWFLAKE.test(channelId) || this.active.size >= 8) return null;
    let chunks = []; let bytes = 0; let soundBytes = 0; let lastSoundEnd = 0;
    let startedAt = null; let closed = false;
    const clear = () => { chunks = []; bytes = 0; soundBytes = 0; lastSoundEnd = 0; startedAt = null; };
    const flush = () => {
      if (lastSoundEnd >= RATE * 2 * 0.6 && soundBytes >= RATE * 2 * 0.4) {
        const pcm = Buffer.concat(chunks, bytes).subarray(0, lastSoundEnd);
        this.enqueue(memberId, pcm, { display_name: String(displayName).slice(0, 128), channel_id: channelId,
          started_at: startedAt, ended_at: new Date().toISOString() });
      }
      clear();
    };
    const session = {
      push: (pcm) => {
        if (closed || !this.eligible(memberId)) return;
        // Native Opus decode is at most 120 ms. Keep interior pauses, trim quiet
        // edges, and require >=400 ms of signal above roughly -46 dBFS RMS.
        if (!pcm.length || pcm.length % 2 || pcm.length > RATE * 2 * 0.12) return;
        let square = 0;
        for (let i = 0; i < pcm.length; i += 2) square += pcm.readInt16LE(i) ** 2;
        const sound = Math.sqrt(square / (pcm.length / 2)) >= 160;
        if (!bytes && !sound) return;
        if (!startedAt) startedAt = new Date().toISOString();
        chunks.push(Buffer.from(pcm)); bytes += pcm.length;
        if (sound) { soundBytes += pcm.length; lastSoundEnd = bytes; }
        if (bytes >= RATE * 2 * this.config.chunk_seconds) flush();
      },
      finish: (keep = true) => {
        if (closed) return;
        closed = true;
        this.active.delete(session);
        if (keep && this.eligible(memberId)) flush(); else clear();
      },
      memberId,
      get closed() { return closed; },
    };
    this.active.add(session);
    return session;
  }

  enqueue(memberId, pcm, timing) {
    if (!this.eligible(memberId)) return;
    const metadata = Buffer.from(`${JSON.stringify({ version: 1, guild_id: this.guildId, member_id: memberId,
      ...timing, sample_rate: RATE, channels: 1, format: 'pcm_s16le', duration_seconds: pcm.length / (RATE * 2),
      consent: { basis: 'owner_attested_all_guild_members', attested_at: this.config.consent_attested_at,
        provenance: this.config.consent_provenance }, purpose: 'bard_voice_training_source', trained: false })}\n`);
    const size = pcm.length + 44 + metadata.length;
    if (this.queuedChunks >= MAX_QUEUED_CHUNKS || this.queuedBytes + size > MAX_QUEUED_BYTES) {
      this.droppedChunks += 1; this.onEvent('sample_write_queue_full'); return;
    }
    this.queuedBytes += size; this.queuedChunks += 1;
    this.queue = this.queue.then(async () => {
      if (!this.eligible(memberId)) return;
      if (this.totalBytes + size > this.config.max_total_bytes) { this.halt('sample_total_quota_reached'); return; }
      if ((this.memberBytes.get(memberId) ?? 0) + size > this.config.max_member_bytes) {
        this.quotaMembers.add(memberId); this.onEvent('sample_member_quota_reached'); return;
      }
      const directory = join(this.directory, memberId);
      await privateDirectory(directory);
      const stem = `${timing.started_at.replace(/[:.]/g, '-')}-${randomUUID()}`;
      // Exclusive creation retains originals even across crashes/restarts. A
      // partial pair after a disk failure remains in place and counts next boot.
      for (const [extension, buffers] of [['wav', [wavHeader(pcm.length), pcm]], ['json', [metadata]]]) {
        const handle = await fs.open(join(directory, `${stem}.${extension}`), 'wx', 0o600);
        try { for (const buffer of buffers) await handle.writeFile(buffer); await handle.sync(); }
        finally { await handle.close(); }
      }
      this.totalBytes += size;
      this.memberBytes.set(memberId, (this.memberBytes.get(memberId) ?? 0) + size);
      this.savedChunks += 1;
    }).catch(() => this.halt('sample_storage_write_failed')).finally(() => {
      this.queuedBytes -= size; this.queuedChunks -= 1;
    });
  }

  control(action, memberId) {
    if (memberId !== undefined && !SNOWFLAKE.test(memberId)) return Promise.reject(new Error('invalid_member_id'));
    if (action === 'status') return Promise.resolve(this.status(memberId));
    const operation = this.controls.then(() => this.applyControl(action, memberId));
    this.controls = operation.catch(() => {});
    return operation;
  }

  async applyControl(action, memberId) {
    if (!SNOWFLAKE.test(memberId)) fail('invalid_member_id');
    if (!['status', 'stop', 'start', 'delete'].includes(action)) fail('invalid_samples_action');
    if (action === 'status') return this.status(memberId);
    if (!this.enabled || !this.ready) fail('samples_not_enabled_or_ready');
    if (action === 'start') {
      if (this.halted) fail('sample_storage_halted');
      this.optedOut.delete(memberId);
    } else {
      if (!this.optedOut.has(memberId) && this.optedOut.size >= MAX_PREFERENCES) fail('sample_preferences_full');
      this.optedOut.add(memberId);
      for (const session of [...this.active]) if (session.memberId === memberId) session.finish(false);
    }
    // Stop/delete drains any already-started write before acknowledging. No new
    // write for this identity can begin after its opt-out latch is set.
    await this.queue;
    try {
      const temporary = `${this.preferencesPath}.${randomUUID()}.tmp`;
      await fs.writeFile(temporary, `${JSON.stringify({ opted_out: [...this.optedOut] })}\n`, { flag: 'wx', mode: 0o600 });
      await fs.rename(temporary, this.preferencesPath);
      if (action === 'delete') {
        await fs.rm(join(this.directory, memberId), { recursive: true, force: true });
        this.totalBytes -= this.memberBytes.get(memberId) ?? 0;
        this.memberBytes.delete(memberId);
        this.quotaMembers.delete(memberId);
        if (this.halted === 'sample_total_quota_reached') this.halted = null;
      }
    } catch { this.halt('sample_storage_write_failed'); fail('sample_storage_write_failed'); }
    return this.status(memberId);
  }

  async drain() { await this.controls; await this.queue; }
}

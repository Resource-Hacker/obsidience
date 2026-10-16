import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import { sampleConfig } from './samples.mjs';

export const MAX_FRAME = 65536;
export const SNOWFLAKE = /^\d{17,20}$/;

async function readPrivateConfig(filename, optional = false) {
  if (optional && !filename) return undefined;
  if (!filename || !path.isAbsolute(filename)) throw new Error('private_config_path_required');
  const stat = await fs.lstat(filename).catch((error) => {
    if (optional && error.code === 'ENOENT') return null;
    throw error;
  });
  if (!stat) return undefined;
  if (!stat.isFile() || stat.uid !== process.getuid() || (stat.mode & 0o077)) {
    throw new Error('private_config_owner_or_mode_invalid');
  }
  if (stat.size > MAX_FRAME) throw new Error('private_config_too_large');
  return JSON.parse(await fs.readFile(filename, 'utf8'));
}

export async function loadConfig(filename) {
  const c = await readPrivateConfig(filename);
  const fields = ['enabled', 'guild_id', 'application_id', 'bot_name', 'allowed_channel_ids', 'message_content_intent'];
  if (Object.keys(c).some((k) => !fields.includes(k))) throw new Error('unknown_config_field');
  if (!SNOWFLAKE.test(c.guild_id) || !SNOWFLAKE.test(c.application_id)) throw new Error('invalid_config_id');
  if (typeof c.bot_name !== 'string' || c.bot_name.length < 2 || c.bot_name.length > 32) throw new Error('invalid_bot_name');
  if (c.enabled !== undefined && typeof c.enabled !== 'boolean') throw new Error('invalid_enabled');
  if (c.message_content_intent !== undefined && typeof c.message_content_intent !== 'boolean') throw new Error('invalid_intent');
  if (c.allowed_channel_ids !== undefined && (!Array.isArray(c.allowed_channel_ids)
      || c.allowed_channel_ids.length > 128 || c.allowed_channel_ids.some((id) => !SNOWFLAKE.test(id)))) {
    throw new Error('invalid_allowed_channels');
  }
  return Object.freeze({ ...c, voice_samples: sampleConfig(await readPrivateConfig(process.env.OBSIDIENCE_DISCORD_SAMPLES_CONFIG, true)), allowed_channel_ids: c.allowed_channel_ids ?? [], message_content_intent: c.message_content_intent === true });
}

export async function credential(name) {
  const directory = process.env.CREDENTIALS_DIRECTORY;
  if (!directory || !path.isAbsolute(directory)) throw new Error('systemd_credentials_required');
  const value = (await fs.readFile(path.join(directory, name), 'utf8')).trim();
  if (!value || value.length > 8192 || /[\r\n]/.test(value)) throw new Error('invalid_credential');
  return value;
}

// Buffers bytes, rather than JS characters, so UTF-8 cannot bypass the frame bound.
export function readFrames(socket, onFrame, onFailure = () => {}) {
  let pending = Buffer.alloc(0);
  let failed = false;
  const fail = () => {
    if (failed) return;
    failed = true;
    socket.destroy();
    onFailure();
  };
  socket.on('data', (chunk) => {
    if (failed) return;
    pending = Buffer.concat([pending, chunk]);
    while (true) {
      const end = pending.indexOf(10);
      if (end < 0) break;
      if (end + 1 > MAX_FRAME) return fail();
      const line = pending.subarray(0, end);
      pending = pending.subarray(end + 1);
      try {
        const value = JSON.parse(line.toString('utf8'));
        if (!value || typeof value !== 'object' || Array.isArray(value)) return fail();
        onFrame(value);
      } catch { return fail(); }
    }
    if (pending.length >= MAX_FRAME) fail();
  });
}

export function sendFrame(socket, value) {
  const frame = Buffer.from(`${JSON.stringify(value)}\n`);
  if (frame.length > MAX_FRAME) throw new Error('frame_too_large');
  if (!socket || socket.destroyed || !socket.writable || socket.writableLength + frame.length > MAX_FRAME * 4) {
    throw new Error('socket_backpressure_or_unavailable');
  }
  socket.write(frame);
}

export async function removeStaleSocket(filename) {
  let stat;
  try { stat = await fs.lstat(filename); } catch (error) { if (error.code === 'ENOENT') return; throw error; }
  if (!stat.isSocket() || stat.uid !== process.getuid()) throw new Error('socket_path_not_owned');
  const active = await new Promise((resolve, reject) => {
    const socket = net.createConnection(filename);
    socket.setTimeout(1000);
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('timeout', () => { socket.destroy(); resolve(true); });
    socket.once('error', (error) => {
      if (['ECONNREFUSED', 'ENOENT'].includes(error.code)) resolve(false);
      else reject(new Error('socket_probe_failed'));
    });
  });
  if (active) throw new Error('transport_already_running');
  const fresh = await fs.lstat(filename).catch(() => null);
  if (fresh?.ino === stat.ino && fresh?.dev === stat.dev) await fs.unlink(filename);
}

import { VoiceConnectionStatus } from '@discordjs/voice';
import { freshVoice } from './admin.mjs';
import { SNOWFLAKE } from './protocol.mjs';

const REQUEST_ID = /^[A-Za-z0-9_-]{8,128}$/;
const fail = (code) => { throw new Error(code); };
const validId = (value) => typeof value === 'string' && SNOWFLAKE.test(value);
const validRequest = (value) => typeof value === 'string' && REQUEST_ID.test(value);

export async function cameraContext(bot, message) {
  const fields = ['command', 'request_id', 'guild_id', 'member_id', 'origin_request_id', 'target_member_id'];
  if (message.command !== 'camera_context' || Object.keys(message).some((key) => !fields.includes(key))) fail('invalid_camera_request');
  if (!validId(message.guild_id) || message.guild_id !== bot.config.guild_id) fail('guild_not_allowed');
  if (!validId(message.member_id)) fail('invalid_member_id');
  if (message.target_member_id !== undefined && !validId(message.target_member_id)) fail('invalid_camera_target');
  if (message.request_id !== undefined && !validRequest(message.request_id)) fail('invalid_request_id');
  if (message.origin_request_id !== undefined && !validRequest(message.origin_request_id)) fail('invalid_camera_origin');

  const generation = bot.generation;
  const channel = bot.channel;
  const connection = bot.connection;
  const turn = message.origin_request_id === undefined ? null : bot.turns.get(message.origin_request_id);
  const current = () => {
    if (bot.closing || !bot.client.isReady() || bot.generation !== generation || !channel || !connection
        || bot.channel !== channel || bot.connection !== connection
        || connection.state.status !== VoiceConnectionStatus.Ready) fail('camera_voice_room_not_current');
    if (message.origin_request_id !== undefined) {
      const principal = turn?.principal;
      if (!turn || bot.turns.get(message.origin_request_id) !== turn || turn.controller.signal.aborted
          || principal.generation !== generation || principal.guild_id !== message.guild_id
          || principal.member_id !== message.member_id || principal.channel_id !== channel.id) fail('camera_origin_not_current');
    }
  };
  current();

  const guild = await (await bot.guild()).fetch();
  if (guild.id !== message.guild_id || channel.guild.id !== guild.id) fail('guild_not_allowed');
  const ids = [...new Set([bot.client.user.id, message.member_id,
    ...(message.target_member_id === undefined ? [] : [message.target_member_id])])];
  const members = new Map(await Promise.all(ids.map(async (id) => [id,
    await guild.members.fetch({ user: id, force: true })])));
  await freshVoice(guild, ids);
  current();
  const requester = members.get(message.member_id);
  const botMember = members.get(bot.client.user.id);
  if (requester.user.bot || requester.voice.channelId !== channel.id || botMember.voice.channelId !== channel.id) {
    fail('camera_requires_joined_voice_room');
  }
  if (message.target_member_id !== undefined) {
    const target = members.get(message.target_member_id);
    if (target.voice.channelId !== channel.id || target.voice.selfVideo !== true) fail('camera_target_not_available');
  }

  // Native room IDs and selfVideo are evidence; display labels are untrusted
  // presentation data and never identify a tile or authorize a capture.
  const room = channel.members;
  const ordered = [...new Set([message.member_id,
    ...(message.target_member_id === undefined ? [] : [message.target_member_id]), ...[...room.keys()].sort()])];
  return { generation, guild_id: guild.id, channel_id: channel.id, channel_name: channel.name.slice(0, 100),
    member_id: requester.id, origin_request_id: message.origin_request_id ?? null,
    target_member_id: message.target_member_id ?? null, observed_at: new Date().toISOString(),
    members: ordered.slice(0, 25).map((id) => members.get(id) ?? room.get(id)).map((member) => ({
      member_id: member.id, display_name: member.displayName.slice(0, 100),
      username: member.user.username.slice(0, 32), camera_enabled: member.voice.selfVideo === true })),
    members_truncated: ordered.length > 25, labels_untrusted: true };
}

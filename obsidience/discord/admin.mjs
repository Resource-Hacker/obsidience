import { PermissionFlagsBits, REST, Routes } from 'discord.js';
import { SNOWFLAKE } from './protocol.mjs';

const REQUEST_ID = /^[A-Za-z0-9_-]{8,128}$/;
const SELECTION_MS = 60_000;
const fail = (code) => { throw new Error(code); };
const activeCommands = ['admin_members', 'admin_kick'];
export const ADMIN_COMMANDS = ['speaker_context', ...activeCommands];

function validate(message) {
  const fields = ['command', 'request_id', 'guild_id', 'member_id'];
  if (activeCommands.includes(message.command)) fields.push('origin_request_id', 'channel_id');
  if (message.command === 'admin_members') fields.push('query');
  if (message.command === 'admin_kick') fields.push('target_member_id', 'reason');
  if (Object.keys(message).some((key) => !fields.includes(key))) fail('invalid_admin_request');
  if (!SNOWFLAKE.test(message.member_id ?? '')) fail('invalid_member_id');
  if (activeCommands.includes(message.command)
      && (!REQUEST_ID.test(message.origin_request_id ?? '') || !SNOWFLAKE.test(message.channel_id ?? ''))) fail('invalid_admin_origin');
  if (message.command === 'admin_members'
      && (message.query !== undefined && (typeof message.query !== 'string' || message.query.length > 100))) fail('invalid_admin_query');
  if (message.command === 'admin_kick'
      && (!SNOWFLAKE.test(message.target_member_id ?? '') || typeof message.reason !== 'string'
        || message.reason.length > 256)) fail('invalid_admin_target_or_reason');
}

function currentTurn(bot, message, expected = null) {
  const turn = bot.turns.get(message.origin_request_id);
  const principal = turn?.principal;
  if (!turn || (expected && turn !== expected) || turn.controller.signal.aborted || bot.closing
      || !bot.client.isReady() || principal.generation !== bot.generation
      || principal.guild_id !== bot.config.guild_id || principal.member_id !== message.member_id
      || principal.channel_id !== message.channel_id) fail('admin_origin_not_current');
  return turn;
}

function administrator(member) {
  return !member.user.bot && member.permissions.has(PermissionFlagsBits.Administrator);
}

function inBotVoice(bot, member, botMember) {
  return !!bot.channel && !!bot.connection && !bot.closing
    && botMember.voice.channelId === bot.channel.id && member.voice.channelId === bot.channel.id;
}

function snapshot(bot, member, botMember) {
  const roles = [...member.roles.cache.values()].filter((role) => role.id !== member.guild.id)
    .sort((a, b) => b.comparePositionTo(a));
  return { member_id: member.id, display_name: member.displayName.slice(0, 100),
    username: member.user.username.slice(0, 32), roles: roles.slice(0, 16)
      .map((role) => ({ role_id: role.id, name: role.name.slice(0, 64) })),
    roles_truncated: roles.length > 16, administrator: administrator(member),
    current_voice_channel_id: member.voice.channelId ?? null, in_bot_voice: inBotVoice(bot, member, botMember) };
}

function kickable(bot, invoker, target) {
  return target.id !== target.guild.ownerId && target.id !== invoker.id && target.id !== bot.client.user.id
    && (invoker.id === target.guild.ownerId || invoker.roles.highest.comparePositionTo(target.roles.highest) > 0)
    && target.kickable;
}

async function freshMembers(bot, memberIds) {
  // Guild owner, role permissions/positions, and each member's role IDs are
  // refreshed from Discord; role names and cached speaker context grant nothing.
  const guild = await (await bot.guild()).fetch();
  await guild.roles.fetch();
  const ids = [...new Set([bot.client.user.id, ...memberIds])];
  const members = new Map(await Promise.all(ids.map(async (id) => [id,
    await guild.members.fetch({ user: id, force: true })])));
  return { guild, members, botMember: members.get(bot.client.user.id) };
}

export async function freshVoice(guild, memberIds) {
  await Promise.all([...new Set(memberIds)].map(async (id) => {
    try { await guild.voiceStates.fetch(id, { force: true }); }
    catch (error) {
      if (error.code !== 10065) throw error;
      // Discord explicitly reports no native voice state; discard a stale
      // Gateway entry rather than authorizing from a departed room member.
      guild.voiceStates.cache.delete(id);
    }
  }));
}

function authorize(bot, message, turn, invoker, botMember) {
  currentTurn(bot, message, turn);
  if (!inBotVoice(bot, invoker, botMember)) fail('admin_requires_joined_voice_room');
  if (!administrator(invoker)) fail('admin_requires_administrator');
}

export async function adminCommand(bot, message) {
  validate(message);
  const turn = activeCommands.includes(message.command) ? currentTurn(bot, message) : null;
  const { guild, members, botMember } = await freshMembers(bot, [message.member_id,
    ...(message.command === 'admin_kick' ? [message.target_member_id] : [])]);
  const invoker = members.get(message.member_id);
  await freshVoice(guild, [invoker.id, botMember.id]);
  if (message.command === 'speaker_context') {
    return { speaker: snapshot(bot, invoker, botMember), advisory: true, labels_untrusted: true };
  }
  authorize(bot, message, turn, invoker, botMember);
  if (turn.adminKickAttempted) fail('admin_kick_already_attempted');

  if (message.command === 'admin_members') {
    const query = (message.query ?? '').trim();
    const exactId = query.match(/^<@!?(\d{17,20})>$/)?.[1] ?? (SNOWFLAKE.test(query) ? query : null);
    let candidates;
    if (exactId) candidates = [await guild.members.fetch({ user: exactId, force: true })];
    else if (query) candidates = [...(await guild.members.search({ query, limit: 10 })).values()];
    else {
      // Empty discovery is bounded to the current room, never a guild-wide dump.
      const ids = [...bot.channel.members.keys()].sort().slice(0, 10);
      candidates = await Promise.all(ids.map((user) => guild.members.fetch({ user, force: true })));
    }
    authorize(bot, message, turn, invoker, botMember);
    const expires = performance.now() + SELECTION_MS;
    turn.adminSelection = new Map(candidates.map((member) => [member.id, expires]));
    return { speaker: snapshot(bot, invoker, botMember), members: candidates.map((member) => ({
      ...snapshot(bot, member, botMember), kickable: kickable(bot, invoker, member) })),
    origin_request_id: message.origin_request_id, channel_id: message.channel_id,
    selection_expires_in_seconds: SELECTION_MS / 1000, labels_untrusted: true };
  }

  const target = members.get(message.target_member_id);
  const expires = turn.adminSelection?.get(target.id);
  if (!expires || performance.now() >= expires) fail('admin_target_not_current_selection');
  if (!kickable(bot, invoker, target)) fail('admin_target_not_kickable');
  await freshVoice(guild, [invoker.id, botMember.id]);
  authorize(bot, message, turn, invoker, botMember);
  if (performance.now() >= expires) fail('admin_target_not_current_selection');
  if (!kickable(bot, invoker, target)) fail('admin_target_not_kickable');

  // GuildMember.kick is a thin guild.members.kick -> rest.delete wrapper in the
  // pinned discord.js. Use that same official endpoint with an isolated REST
  // manager so this effect never inherits its ordinary network/5xx/429 retries.
  const rest = new REST({ version: '10', retries: 0, timeout: 10_000,
    rejectOnRateLimit: () => true }).setToken(bot.client.token);
  const receipt = { target_member_id: target.id, correction_allowed: false };
  turn.adminKickAttempted = true;
  turn.adminSelection = null;
  try {
    try {
      const reason = message.reason.trim();
      await rest.delete(Routes.guildMember(guild.id, target.id), reason ? { reason } : {});
    } catch (error) {
      const denied = error.name === 'RateLimitError'
        || (Number.isInteger(error.status) && error.status >= 400 && error.status < 500 && error.status !== 408);
      return { ...receipt, ok: false, error: denied ? 'admin_kick_denied' : 'admin_kick_delivery_uncertain',
        delivery: denied ? 'not_dispatched' : 'uncertain', effect_applied: denied ? false : null };
    }
    try {
      await rest.get(Routes.guildMember(guild.id, target.id));
    } catch (error) {
      if (error.code === 10007) return { ...receipt, kicked: true, delivery: 'confirmed', effect_applied: true };
    }
    return { ...receipt, ok: false, error: 'admin_kick_verification_inconclusive',
      delivery: 'uncertain', effect_applied: null };
  } finally {
    rest.clearHashSweeper();
    rest.clearHandlerSweeper();
  }
}

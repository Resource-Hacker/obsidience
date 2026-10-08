#!/usr/bin/env node
// Explicit offline upgrade utility. No model, agent, tools, or live services are loaded.
import { readdir, readFile, writeFile, mkdir, access } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { isDeepStrictEqual } from 'node:util';

const [modulesArg, inputArg, outputArg, reportArg] = process.argv.slice(2);
if (!reportArg) throw new Error('Usage: node migrate-sessions.mjs NODE_MODULES SOURCE_COPY NEW_DESTINATION REPORT_JSON');
const modules = resolve(modulesArg), input = resolve(inputArg), output = resolve(outputArg);
if (input === output || output.startsWith(input + '/')) throw new Error('Destination must be separate from source');
try { await access(output); throw new Error('Destination already exists; refusing overwrite'); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
const require = createRequire(join(modules, '../package.json'));
const load = name => import(pathToFileURL(require.resolve('@deepseek-ai/' + name)).href);
const [{ Context }, { default: JsonlPersistence }, { Session }, { createSessionFormatCatalogWithChildren }, { currentSessionMessageProjections }] = await Promise.all([
  load('cordis'), load('dsh-session-persistence-jsonl'), load('dsh-session'), load('dsh-session-format-catalog'),
  load('dsh-session-format-catalog/message-projections'),
]);
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
async function files(root) {
  const result = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error('Source contains symlink: ' + path);
    if (entry.isDirectory()) result.push(...await files(path));
    else if (/^session\.v[34]\.jsonl(?:\.zstd)?$/.test(entry.name)) result.push(path);
  }
  return result.sort();
}
const report = { input, output, packageVersion: '0.2.0-rc.2', sessions: [], skippedCurrent: [], blockers: [] };
const prepared = [], ids = new Set(), catalog = createSessionFormatCatalogWithChildren([]);
for (const path of await files(input)) {
  const bytes = await readFile(path), sourceSha256 = sha(bytes);
  if (path.includes('/session.v4.')) { report.skippedCurrent.push({ path, sourceSha256 }); continue; }
  const row = { path, sourceSha256 };
  try {
    await access(path.replace('/session.v3.', '/session.v4.'));
    throw new Error('V4 successor already exists; refusing stale V3 import: ' + path);
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  report.sessions.push(row);
  try {
    const decoded = path.endsWith('.zstd') ? execFileSync('/usr/bin/zstd', ['--decompress', '--stdout', '--', path], { maxBuffer: 64 * 1024 * 1024 }) : bytes;
    const lines = decoded.toString('utf8').split('\n');
    if (lines.at(-1) === '') lines.pop();
    const header = JSON.parse(lines.shift());
    if (header.version !== 3 || header.isSeeded || header.parentSession !== undefined || header.origin !== undefined || header.delegationDepth !== 0) throw new Error('Only unseeded, non-delegated V3 sessions are supported');
    if (ids.has(header.id)) throw new Error('Duplicate source id ' + header.id);
    ids.add(header.id);
    const restore = catalog.createRestore(header, { recovery: 'strict', validation: 'transformed' });
    for (const line of lines) {
      const physical = JSON.parse(line);
      if (typeof physical.type === 'string' && (physical.type.startsWith('subagent/') || (physical.type === 'session/end-seed' && physical.data?.inherited === true))) throw new Error('Child/seed event requires explicit historical evidence');
      restore.decodeRow(physical);
    }
    const artifact = restore.finish();
    // Ordinary end-seed lifecycle markers do not represent fork inheritance.
    if (artifact.inheritedEventCount !== 0 || artifact.events.some(e => e.type.startsWith('subagent/') || (e.type === 'session/end-seed' && e.data?.inherited === true))) throw new Error('Unsupported child/seed history');
    const changes = [];
    const events = artifact.events.map(event => {
      if (event.type !== 'system/message') return event;
      const message = event.data.message;
      if (message.source.kind === 'system-prompt') return event;
      if (!isDeepStrictEqual(message.source, { kind: 'plugin:obsidience' })) throw new Error('Unexpected system producer at seq ' + event.seq);
      const originalSource = { kind: 'plugin', plugin: 'obsidience' };
      const source = { kind: 'system-prompt', 'obsidience.originalSource': originalSource };
      changes.push({ seq: event.seq, messageId: message.id, originalSource, upstreamMigratedSource: message.source, successorSource: source, contentSha256: sha(JSON.stringify(message.content)) });
      return { ...event, data: { ...event.data, message: { ...message, source } } };
    });
    const validated = Session.fromRestore(header.id, events, artifact.header, artifact.inheritedEventCount, 'detached', currentSessionMessageProjections);
    row.id = header.id; row.eventCount = events.length; row.provenanceChanges = changes;
    row.upstreamArtifactSha256 = sha(JSON.stringify(artifact));
    row.successorLogicalSha256 = sha(JSON.stringify({ header: artifact.header, inheritedEventCount: artifact.inheritedEventCount, events }));
    prepared.push({ row, header: validated.header, events: validated.snapshotEvents() });
  } catch (error) { row.error = error.message; report.blockers.push({ path, error: error.message }); }
}
if (report.blockers.length) {
  await writeFile(reportArg, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
  throw new Error(`Refused entire migration: ${report.blockers.length} unsupported sources; report ${reportArg}`);
}
await mkdir(output, { recursive: false, mode: 0o700 });
const ctx = new Context();
const fiber = await ctx.plugin(JsonlPersistence, { root: output });
try {
  for (const item of prepared) {
    const writer = await ctx.sessionPersistence.create(item.header, { inheritedEventCount: 0 });
    try { await writer.append(item.events); await writer.flush(); } finally { await writer.close(); }
    const reader = await ctx.sessionPersistence.open(item.header.id, 'read');
    try {
      const reread = await reader.read();
      if (!isDeepStrictEqual(reread.events, item.events)) throw new Error('Persistence round trip changed events for ' + item.header.id);
      if (!isDeepStrictEqual(reader.header, item.header) || reader.inheritedEventCount !== 0) throw new Error('Persistence round trip changed header/cut');
    } finally { await reader.close(); }
  }
} finally { await fiber.dispose(); }
const successors = await files(output);
report.successorFiles = await Promise.all(successors.map(async path => ({ path, sha256: sha(await readFile(path)) })));
for (const row of [...report.sessions, ...report.skippedCurrent]) {
  if (sha(await readFile(row.path)) !== row.sourceSha256) throw new Error('Source changed during migration: ' + row.path);
}
report.sourceBytesUnchanged = true;
report.migratedSessionCount = prepared.length;
await writeFile(reportArg, JSON.stringify(report, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
console.log(JSON.stringify({ migrated: prepared.length, provenanceCorrections: report.sessions.reduce((n, s) => n + s.provenanceChanges.length, 0), skippedCurrent: report.skippedCurrent.length, sourceBytesUnchanged: true, report: reportArg }));

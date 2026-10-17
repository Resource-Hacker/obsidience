import './bootstrap.mjs';
import { chmodSync, lstatSync, mkdirSync, unlinkSync } from 'node:fs';
import { createServer } from 'node:net';
import { join } from 'node:path';
import { ControllerBehavior, Environment, Logger, Seconds, ServerNode } from '@matter/main';
import { OnOffClient } from '@matter/main/behaviors/on-off';
import { LevelControlClient } from '@matter/main/behaviors/level-control';
import { ColorControlClient } from '@matter/main/behaviors/color-control';
import { installEncryptedStorage } from './encrypted-storage.mjs';

// Dependency diagnostics may include commissioning data. Publish only our bounded safe events.
for (const destination of Object.values(Logger.destinations)) destination.add = () => {};
process.umask(0o077);
const fixtures = new Set(['window_lamp', 'woven_pendant', 'north_lamp', 'tv_floor_lamp', 'desk_lantern', 'room_lantern']);
const runtime = process.env.OBSIDIENCE_MATTER_RUNTIME ?? join(process.env.XDG_RUNTIME_DIR ?? '/unavailable', 'obsidience-lights');
const state = process.env.OBSIDIENCE_MATTER_STATE ?? join(process.env.HOME ?? '/unavailable', '.local/state/obsidience-lights');
const socketPath = join(runtime, 'control.sock');
const keyPath = join(process.env.CREDENTIALS_DIRECTORY ?? '/unavailable', 'matter-key');
let controller, server, closing = false;
const queues = new Map();
const sockets = new Set();
let storage;

function invalid() { throw new Error('invalid_request'); }
function integer(value, min, max) { if (!Number.isInteger(value) || value < min || value > max) invalid(); return value; }
function exactKeys(value, allowed) { if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !allowed.includes(key))) invalid(); }
function targetOf(request) { if (!fixtures.has(request.target)) invalid(); return request.target; }
function peerInfo(peer) {
    return { target: peer.id, commissioned: peer.lifecycle.isCommissioned,
        nodeId: peer.peerAddress?.nodeId?.toString(),
        endpoints: [...peer.endpoints].filter(endpoint => endpoint.behaviors.has(OnOffClient)).map(endpoint => endpoint.number) };
}
async function endpointOf(request) {
    const peer = controller.peers.get(targetOf(request));
    if (!peer?.lifecycle.isCommissioned) throw new Error('not_commissioned');
    if (request.nodeId !== undefined && (typeof request.nodeId !== 'string' || request.nodeId !== peer.peerAddress?.nodeId?.toString())) throw new Error('binding_mismatch');
    await peer.start();
    const candidates = [...peer.endpoints].filter(endpoint => endpoint.behaviors.has(OnOffClient));
    const endpoint = request.endpoint === undefined
        ? (candidates.length === 1 ? candidates[0] : undefined)
        : candidates.find(endpoint => endpoint.number === integer(request.endpoint, 1, 65534));
    if (!endpoint) throw new Error('endpoint_not_unique');
    return { peer, endpoint };
}
async function readState(peer, endpoint) {
    const selectors = {};
    for (const [behavior, attributes] of [
        [OnOffClient, ['onOff']], [LevelControlClient, ['currentLevel']],
        [ColorControlClient, ['colorMode', 'currentX', 'currentY', 'currentHue', 'currentSaturation', 'colorTemperatureMireds']],
    ]) {
        if (!endpoint.behaviors.has(behavior)) continue;
        const present = endpoint.behaviors.elementsOf(behavior).attributes;
        const supported = attributes.filter(name => present.has(name));
        if (supported.length) selectors[behavior.id] = supported;
    }
    // Endpoint.get explicitly issues a remote Matter Read. includeKnownVersions prevents
    // data-version filters from replacing physical readback with cached state.
    const result = await endpoint.get(selectors, { includeKnownVersions: true });
    return { target: peer.id, nodeId: peer.peerAddress.nodeId.toString(), endpoint: endpoint.number,
        ...result.onOff, ...result.levelControl, ...result.colorControl, fresh: true };
}
function validateSet(request) {
    exactKeys(request, ['command', 'target', 'nodeId', 'endpoint', 'onOff', 'level', 'color', 'readback']);
    targetOf(request);
    if (typeof request.nodeId !== 'string' || !/^\d{1,20}$/.test(request.nodeId) || request.endpoint === undefined) invalid();
    if (request.endpoint !== undefined) integer(request.endpoint, 1, 65534);
    if (request.readback !== undefined && typeof request.readback !== 'boolean') invalid();
    if (request.onOff !== undefined && typeof request.onOff !== 'boolean') invalid();
    if (request.level !== undefined) integer(request.level, 0, 254);
    if (request.color !== undefined) {
        const c = request.color;
        if (c?.mode === 'xy') { exactKeys(c, ['mode', 'x', 'y']); integer(c.x, 0, 65279); integer(c.y, 0, 65279); }
        else if (c?.mode === 'hs') { exactKeys(c, ['mode', 'hue', 'saturation']); integer(c.hue, 0, 254); integer(c.saturation, 0, 254); }
        else if (c?.mode === 'temperature') { exactKeys(c, ['mode', 'mireds']); integer(c.mireds, 1, 65279); }
        else invalid();
    }
    if (request.onOff === undefined && request.level === undefined && request.color === undefined) invalid();
}
async function dispatch(request, socket) {
    if (closing) throw new Error('shutting_down');
    storage.assertHealthy();
    exactKeys(request, ['command', 'target', 'nodeId', 'endpoint', 'onOff', 'level', 'color', 'readback', 'pairingCode', 'seconds']);
    switch (request.command) {
        case 'status':
            exactKeys(request, ['command']);
            return { protocol: 'matter', library: '0.17.9', targets: [...controller.peers].filter(p => p.lifecycle.isCommissioned).map(peerInfo) };
        case 'discover': {
            exactKeys(request, ['command', 'seconds']);
            const seconds = request.seconds === undefined ? 8 : integer(request.seconds, 1, 30);
            const found = await controller.peers.discover({ timeout: Seconds(seconds) });
            return { devices: found.map(peer => {
                const data = peer.maybeStateOf('commissioning');
                return { id: peer.id, vendorId: data?.vendorId, productId: data?.productId, discriminator: data?.discriminator, deviceName: data?.deviceName };
            }) };
        }
        case 'commission': {
            exactKeys(request, ['command', 'target', 'pairingCode']);
            const target = targetOf(request);
            if (controller.peers.get(target)?.lifecycle.isCommissioned) throw new Error('already_commissioned');
            // Manual setup code only; never echo, persist in our API, log, or accept as argv/env.
            if (typeof request.pairingCode !== 'string' || !/^\d{11}(?:\d{10})?$/.test(request.pairingCode)) invalid();
            try {
                // Discovery retains uncommissioned peerN records; its id option only applies
                // to newly created peers. Drop those local records so this request's exact
                // fixture alias becomes the persisted peer id. No commissioned peer is removed.
                for (const candidate of [...controller.peers]) {
                    if (!candidate.lifecycle.isCommissioned) await candidate.delete();
                }
                const peer = await controller.peers.commission({ id: target, pairingCode: request.pairingCode,
                    discoveryCapabilities: { onIpNetwork: true, ble: false }, timeout: Seconds(120), autoSubscribe: true });
                if (peer.id !== target) throw new Error('binding_mismatch');
                return { ...peerInfo(peer), delivery: 'commissioned' };
            } finally { request.pairingCode = undefined; }
        }
        case 'read': {
            exactKeys(request, ['command', 'target', 'endpoint']);
            const { peer, endpoint } = await endpointOf(request);
            return await readState(peer, endpoint);
        }
        case 'set': {
            validateSet(request);
            const { peer, endpoint } = await endpointOf(request);
            const operations = [];
            const options = { transitionTime: 0, optionsMask: { executeIfOff: true }, optionsOverride: { executeIfOff: true } };
            function command(behavior, name, args) {
                if (!endpoint.behaviors.has(behavior) || !endpoint.behaviors.elementsOf(behavior).commands.has(name)) throw new Error('unsupported_command');
                operations.push(() => args === undefined ? endpoint.commandsOf(behavior)[name]() : endpoint.commandsOf(behavior)[name](args));
            }
            // Validate every command before any dispatch. Set color and level while off, then power.
            if (request.color) {
                const c = request.color;
                if (c.mode === 'xy') command(ColorControlClient, 'moveToColor', { ...options, colorX: c.x, colorY: c.y });
                if (c.mode === 'hs') command(ColorControlClient, 'moveToHueAndSaturation', { ...options, hue: c.hue, saturation: c.saturation });
                if (c.mode === 'temperature') command(ColorControlClient, 'moveToColorTemperature', { ...options, colorTemperatureMireds: c.mireds });
            }
            if (request.level !== undefined) command(LevelControlClient, request.onOff === true && request.level > 0 ? 'moveToLevelWithOnOff' : 'moveToLevel', { ...options, level: request.level });
            if (request.onOff !== undefined && !(request.onOff === true && request.level > 0)) command(OnOffClient, request.onOff ? 'on' : 'off');
            let acknowledged = 0;
            try {
                for (const operation of operations) {
                    if (socket.destroyed) throw new Error('caller_disconnected');
                    await operation(); acknowledged++;
                }
                const result = { target: peer.id, nodeId: peer.peerAddress.nodeId.toString(), endpoint: endpoint.number,
                    delivery: 'acknowledged', commandsAcknowledged: acknowledged, effectVerified: false, transitionTime: 0 };
                if (request.readback !== false) result.state = await readState(peer, endpoint);
                return result;
            } catch {
                return { ok: false, error: { code: 'matter_operation_failed' }, delivery: 'uncertain', commandsAcknowledged: acknowledged, effectVerified: false, mustNotReplay: true };
            }
        }
        case 'shutdown':
            exactKeys(request, ['command']);
            setImmediate(shutdown);
            return { delivery: 'accepted' };
        default: invalid();
    }
}

// One native fabric owner; different lights may execute concurrently. Each fixture has a
// bounded serialized lane. Administrative discovery/commission operations share a lane.
function enqueue(request, socket) {
    exactKeys(request, ['command', 'target', 'nodeId', 'endpoint', 'onOff', 'level', 'color', 'readback', 'pairingCode', 'seconds']);
    const key = fixtures.has(request.target) && ['read', 'set'].includes(request.command) ? request.target : '$admin';
    const lane = queues.get(key) ?? { tail: Promise.resolve(), pending: 0 };
    if (lane.pending >= 8) return Promise.reject(new Error('busy'));
    lane.pending++;
    const result = lane.tail.then(() => {
        if (socket.destroyed) throw new Error('caller_disconnected');
        return dispatch(request, socket);
    });
    lane.tail = result.catch(() => {}).finally(() => { lane.pending--; if (!lane.pending) queues.delete(key); });
    queues.set(key, lane);
    return result;
}
async function shutdown() {
    if (closing) return;
    closing = true;
    server?.close();
    await Promise.all([...queues.values()].map(lane => lane.tail));
    await controller?.close();
    for (const socket of sockets) socket.destroy();
    try { unlinkSync(socketPath); } catch {}
    process.exit(0);
}
const safeCodes = new Set(['invalid_request', 'not_commissioned', 'endpoint_not_unique', 'already_commissioned', 'busy', 'storage_unavailable', 'unsupported_command', 'binding_mismatch', 'shutting_down', 'caller_disconnected']);
try {
    storage = installEncryptedStorage(Environment.default, state, keyPath);
    mkdirSync(runtime, { recursive: true, mode: 0o700 });
    const stat = lstatSync(runtime);
    if (!stat.isDirectory() || stat.uid !== process.getuid() || (stat.mode & 0o077)) throw new Error('runtime_permissions');
    controller = await ServerNode.create(ServerNode.RootEndpoint.with(ControllerBehavior), {
        id: 'obsidience-lights', controller: { adminFabricLabel: 'Obsidience Lights', ble: false },
        commissioning: { enabled: false }, network: { port: 0, ble: false },
    });
    await controller.start();
    // The service's flock is held before startup; a leftover socket is safe to remove here.
    try { const old = lstatSync(socketPath); if (!old.isSocket() || old.uid !== process.getuid()) throw new Error('socket_permissions'); unlinkSync(socketPath); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    server = createServer(socket => {
        if (sockets.size >= 64) { socket.destroy(); return; }
        sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.on('error', () => {});
        socket.setTimeout(3000, () => socket.destroy());
        let data = '', accepted = false;
        socket.on('data', chunk => {
            if (accepted) { socket.destroy(); return; }
            data += chunk.toString('utf8');
            if (Buffer.byteLength(data) > 8192) { socket.destroy(); return; }
            if (!data.includes('\n')) return;
            accepted = true;
            socket.setTimeout(150000);
            let request;
            try { request = JSON.parse(data.trim()); exactKeys(request, ['command', 'target', 'nodeId', 'endpoint', 'onOff', 'level', 'color', 'readback', 'pairingCode', 'seconds']); } catch { socket.end('{"ok":false,"error":{"code":"invalid_request"},"delivery":"not_dispatched"}\n'); return; }
            data = '';
            enqueue(request, socket).then(result => socket.end(JSON.stringify(result.ok === false ? result : { ok: true, result }) + '\n'), error => {
                socket.end(JSON.stringify({ ok: false, error: { code: safeCodes.has(error.message) ? error.message : 'matter_operation_failed' }, delivery: request.command === 'commission' ? 'uncertain' : 'not_dispatched', mustNotReplay: true }) + '\n');
            });
        });
    });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(socketPath, resolve); });
    chmodSync(socketPath, 0o600);
    process.stdout.write('{"event":"ready","protocol":"matter"}\n');
    process.on('SIGTERM', () => shutdown().catch(() => process.exit(1)));
    process.on('SIGINT', () => shutdown().catch(() => process.exit(1)));
    process.on('uncaughtException', () => { process.stderr.write('{"event":"runtime_failed"}\n'); process.exit(1); });
    process.on('unhandledRejection', () => { process.stderr.write('{"event":"runtime_failed"}\n'); process.exit(1); });
} catch {
    process.stderr.write('{"event":"startup_failed"}\n');
    await controller?.close().catch(() => {});
    process.exit(1);
}

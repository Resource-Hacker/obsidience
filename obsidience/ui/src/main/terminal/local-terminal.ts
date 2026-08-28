/** Fixed local tmux mirror for the current Codex workspace. */

import { spawnSync, type SpawnSyncReturns } from "node:child_process";
import { homedir } from "node:os";
import { spawn as spawnPty, type IDisposable, type IPty } from "node-pty";

export const LOCAL_TERMINAL_GROUP = "codex";
export const LOCAL_TERMINAL_SESSION = "obsidience-ui";
export const LOCAL_TERMINAL_SOURCE_SESSION = "codex-dp4";
export const LOCAL_TERMINAL_LABEL = "codex tmux";

const TMUX_BINARY = "/usr/bin/tmux";
const SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MIN_COLS = 20;
const MAX_COLS = 320;
const MIN_ROWS = 8;
const MAX_ROWS = 160;
const MAX_INPUT_CHARS = 65_536;
const TMUX_WINDOW_ID = /^@[0-9]+$/;

export interface LocalTerminalSize { cols: number; rows: number }
export interface LocalTerminalOpenRequest extends LocalTerminalSize { sessionId: string }
export interface LocalTerminalOpenResult {
  sessionId: string;
  label: typeof LOCAL_TERMINAL_LABEL;
  linkedSession: typeof LOCAL_TERMINAL_SESSION;
  windowCols: number;
  windowRows: number;
  pid: number;
}
export interface LocalTerminalExit {
  sessionId: string;
  exitCode: number;
  signal?: number;
}

interface TerminalRecord {
  ownerId: number;
  pty: IPty;
  dataSubscription: IDisposable;
  exitSubscription: IDisposable;
}

type CommandRunner = (file: string, args: readonly string[]) => SpawnSyncReturns<string>;

function runCommand(file: string, args: readonly string[]): SpawnSyncReturns<string> {
  return spawnSync(file, [...args], { encoding: "utf8", timeout: 2_000, windowsHide: true });
}

function boundedMessage(result: SpawnSyncReturns<string>): string {
  const value = result.stderr || result.stdout || result.error?.message || "unknown error";
  return value.replace(/[\r\n]+/g, " ").trim().slice(0, 240);
}

function parseSize(value: unknown): LocalTerminalSize {
  if (!value || typeof value !== "object") throw new Error("Terminal dimensions are required.");
  const { cols, rows } = value as Partial<LocalTerminalSize>;
  if (!Number.isSafeInteger(cols) || !Number.isSafeInteger(rows)
      || (cols as number) < MIN_COLS || (cols as number) > MAX_COLS
      || (rows as number) < MIN_ROWS || (rows as number) > MAX_ROWS) {
    throw new Error("Terminal dimensions are outside the supported range.");
  }
  return { cols: cols as number, rows: rows as number };
}

function parseSessionId(value: unknown): string {
  if (typeof value !== "string" || !SESSION_ID.test(value)) {
    throw new Error("Terminal session ID is invalid.");
  }
  return value;
}

/** Main owns the command and one PTY; renderer receives only bytes and dimensions. */
export class LocalTerminalManager {
  private readonly sessions = new Map<string, TerminalRecord>();

  constructor(private readonly options: {
    onData: (ownerId: number, sessionId: string, data: string) => void;
    onExit: (ownerId: number, event: LocalTerminalExit) => void;
    env?: NodeJS.ProcessEnv;
    cwd?: string;
    commandRunner?: CommandRunner;
  }) {}

  open(ownerId: number, rawRequest: unknown): LocalTerminalOpenResult {
    if (!Number.isSafeInteger(ownerId) || ownerId < 1) throw new Error("Terminal owner is invalid.");
    if (!rawRequest || typeof rawRequest !== "object") throw new Error("Terminal request is invalid.");
    const request = rawRequest as Partial<LocalTerminalOpenRequest>;
    const sessionId = parseSessionId(request.sessionId);
    const size = parseSize(request);
    if (this.sessions.has(sessionId)) throw new Error("Terminal session already exists.");

    this.closeOwner(ownerId);
    this.ensureLinkedSession();
    const tmuxWindowSize = this.inspectTmuxWindowSize(size);
    const terminal = spawnPty(
      TMUX_BINARY,
      ["attach-session", "-f", "ignore-size", "-t", `=${LOCAL_TERMINAL_SESSION}`],
      {
        name: "xterm-256color",
        cols: size.cols,
        rows: size.rows,
        cwd: this.options.cwd ?? homedir(),
        env: {
          ...(this.options.env ?? process.env),
          TERM: "xterm-256color",
          COLORTERM: "truecolor",
        },
        encoding: "utf8",
      },
    );

    const record = {} as TerminalRecord;
    record.ownerId = ownerId;
    record.pty = terminal;
    record.dataSubscription = terminal.onData((data) => {
      if (this.sessions.get(sessionId) === record) {
        this.options.onData(ownerId, sessionId, data.slice(0, 262_144));
      }
    });
    record.exitSubscription = terminal.onExit(({ exitCode, signal }) => {
      if (this.sessions.get(sessionId) !== record) return;
      this.sessions.delete(sessionId);
      record.dataSubscription.dispose();
      record.exitSubscription.dispose();
      this.options.onExit(ownerId, { sessionId, exitCode, signal });
    });
    this.sessions.set(sessionId, record);
    return {
      sessionId,
      label: LOCAL_TERMINAL_LABEL,
      linkedSession: LOCAL_TERMINAL_SESSION,
      windowCols: tmuxWindowSize.cols,
      windowRows: tmuxWindowSize.rows,
      pid: terminal.pid,
    };
  }

  write(ownerId: number, rawSessionId: unknown, rawData: unknown): void {
    const record = this.ownedRecord(ownerId, rawSessionId);
    if (typeof rawData !== "string" || rawData.length > MAX_INPUT_CHARS) {
      throw new Error("Terminal input is invalid.");
    }
    record.pty.write(rawData);
  }

  resize(ownerId: number, rawSessionId: unknown, rawSize: unknown): void {
    const record = this.ownedRecord(ownerId, rawSessionId);
    const size = parseSize(rawSize);
    record.pty.resize(size.cols, size.rows);
  }

  close(ownerId: number, rawSessionId: unknown): boolean {
    const sessionId = parseSessionId(rawSessionId);
    const record = this.sessions.get(sessionId);
    if (!record || record.ownerId !== ownerId) return false;
    this.stopRecord(sessionId, record);
    return true;
  }

  closeOwner(ownerId: number): void {
    for (const [sessionId, record] of this.sessions) {
      if (record.ownerId === ownerId) this.stopRecord(sessionId, record);
    }
  }

  dispose(): void {
    for (const [sessionId, record] of this.sessions) this.stopRecord(sessionId, record);
  }

  private ownedRecord(ownerId: number, rawSessionId: unknown): TerminalRecord {
    const record = this.sessions.get(parseSessionId(rawSessionId));
    if (!record || record.ownerId !== ownerId) throw new Error("Terminal session is unavailable.");
    return record;
  }

  private stopRecord(sessionId: string, record: TerminalRecord): void {
    if (this.sessions.get(sessionId) !== record) return;
    this.sessions.delete(sessionId);
    record.dataSubscription.dispose();
    record.exitSubscription.dispose();
    try { record.pty.kill(); } catch { /* tmux session intentionally survives */ }
  }

  private command(file: string, args: readonly string[]): SpawnSyncReturns<string> {
    return (this.options.commandRunner ?? runCommand)(file, args);
  }

  private ensureLinkedSession(): void {
    const exists = this.command(TMUX_BINARY, ["has-session", "-t", `=${LOCAL_TERMINAL_SESSION}`]);
    if (exists.status === 1) {
      const created = this.command(TMUX_BINARY, [
        "new-session", "-d", "-t", `=${LOCAL_TERMINAL_GROUP}`, "-s", LOCAL_TERMINAL_SESSION,
      ]);
      if (created.status !== 0) {
        throw new Error(`Unable to link the local tmux session: ${boundedMessage(created)}`);
      }
    } else if (exists.status !== 0) {
      throw new Error(`Unable to inspect the local tmux session: ${boundedMessage(exists)}`);
    }
    // Mirror whichever window the physical Codex client currently owns. The
    // external window name is presentation state, not an Obsidience concept.
    const target = this.sourceWindowTarget();
    if (target) this.command(TMUX_BINARY, ["select-window", "-t", target]);
  }

  private inspectTmuxWindowSize(fallback: LocalTerminalSize): LocalTerminalSize {
    const target = this.sourceWindowTarget() ?? `=${LOCAL_TERMINAL_SESSION}`;
    const inspected = this.command(TMUX_BINARY, [
      "display-message", "-p", "-t", target,
      "#{window_width} #{window_height}",
    ]);
    if (inspected.status !== 0) return fallback;
    const [cols, rows] = inspected.stdout.trim().split(/\s+/, 2).map(Number);
    try { return parseSize({ cols, rows }); } catch { return fallback; }
  }

  private sourceWindowTarget(): string | null {
    const inspected = this.command(TMUX_BINARY, [
      "display-message", "-p", "-t", `=${LOCAL_TERMINAL_SOURCE_SESSION}`,
      "#{window_id}",
    ]);
    const target = inspected.stdout.trim();
    return inspected.status === 0 && TMUX_WINDOW_ID.test(target) ? target : null;
  }
}

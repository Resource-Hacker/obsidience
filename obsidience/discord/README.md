# Obsidience Discord Bot

Bard is an official Discord bot transport for the independently configured
Obsidience Discord Agent. The Harness owns that Agent's identity, Knowledge,
conversation, grants and reasoning. This process owns Discord Gateway, voice,
receivers and audio players. The existing speech worker owns ASR, wake admission,
followups and TTS; this package loads no speech or language model.

Each member uses a separate decoder stream. After a packet gap, the speech owner
finishes the existing bounded endpoint silence, drains recognition and pending
wake confirmation, then retires unaddressed stream state. The next utterance
starts fresh without reloading model weights. Claimed commands and question
followups retain their speaker ownership. Generated endpoint silence does not
count toward the continuous received-audio limit.
VAD and turn detection receive the full endpoint window; ASR receives only its
existing finite silence tail, ending on a complete decoder batch. Actual member
audio, including quiet speech, is always recognized while that member is eligible
to listen. This prevents idle streams from competing with current speakers for
the shared decoder. Private diagnostics retain bounded per-member failure codes
and queue counts after a failed stream is removed, without audio or transcript text.

Wake recognition uses the ordinary desktop wake-address matcher with `Bard`
(for example, “Hey Bard”), including its sentence-start/pause and possessive guards.
There is no name-specific alias list or biased decoder. A question followup
retains its original member without requiring a new
wake name; ordinary listening always requires an address.

Discord's supported bot voice API carries audio. Local video files can supply their
audio track, but this implementation does not transmit video or Go Live streams.
It uses no user account, user token, selfbot, screen capture or hidden client API.

## Dependencies

Node >=22.12, `/usr/bin/ffmpeg`, and `npm ci` in this directory are required.
`package-lock.json` pins the complete Node dependency graph. `package.json` permits
only the pinned native `@discordjs/opus@0.10.0` installation script; older npm
versions run native dependency scripts normally. FFmpeg is the installed CPU
resampler/decoder, not an npm-downloaded binary.

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| discord.js | 14.27.0 | Apache-2.0 | Official bot Gateway and REST adapter |
| @discordjs/voice | 0.19.2 | Apache-2.0 | DAVE-capable voice receive and playback |
| @discordjs/opus | 0.10.0 | MIT | Native libopus decode/encode |
| @snazzah/davey | 0.1.12 (lockfile) | MIT | Upstream voice dependency, DAVE encryption |

Upstream references: [discord.js](https://github.com/discordjs/discord.js),
[voice installation](https://discordjs.guide/voice),
[voice 0.19.2 changelog](https://github.com/discordjs/discord.js/blob/main/packages/voice/CHANGELOG.md),
[Opus binding](https://github.com/discordjs/opus). Voice receive is bounded and
failure-visible; DAVE and audible acceptance still require a real joined channel.

## Private installation

Create an official bot application in the Discord Developer Portal. Install only
into the configured guild with `bot` and `applications.commands` scopes. It needs
View Channels, Send Messages, Connect and Speak in the intended channels; Change
Nickname is optional. Administrator, Guild Members and Message Content privileged
intents are unnecessary for slash commands. Discord makes directly mentioned
messages available to bots without privileged Message Content; ordinary ambient
messages are ignored. `message_content_intent: true` is an explicit optional
private setting and must also be granted in the Developer Portal.

The private owner-only JSON at `OBSIDIENCE_DISCORD_CONFIG` contains:

```json
{
  "enabled": true,
  "guild_id": "YOUR_GUILD_ID",
  "application_id": "YOUR_APPLICATION_ID",
  "bot_name": "Bard",
  "allowed_channel_ids": [],
  "message_content_intent": false
}
```

IDs and configuration belong only in the ignored installation state. An empty
channel allowlist allows ordinary voice channels in the single configured guild;
a nonempty list restricts voice join and mention handling to those exact channels.
The Harness independently checks ingress identities and channel policy. The bot
never joins automatically at startup or follows a moderator move. It joins only
through an explicit current slash command or owner control request.

The service reads only `discord-bot-token` and `discord-ingress-token` from
systemd's `CREDENTIALS_DIRECTORY`. Keep their encrypted files under
`~/.config/credentials/`; never put tokens in JSON, argv, environment, README,
Gateway exception output or logs. The unit template names the encrypted files
`obsidience-discord-bot-token.cred` and `obsidience-discord-ingress-token.cred`.
Its journal contains fixed event/error codes, no user text or raw API exceptions.

The provided user unit is deliberately opt-in and has no automatic restart.
Install it only after the existing speech owner enables its Discord socket.
Start/restart returns disconnected; joining again requires an explicit request.
Stopping the unit kills its FFmpeg children through the same service cgroup.

## Discord commands

The bot registers guild-scoped `/join`, `/leave`, `/status`, `/ask text`, `/stop`.
`/join` joins the invoker's current voice channel when both bot and invoker have
Connect/Speak; moving an already joined bot to another channel requires Manage
Server. `/leave` and `/stop` require Manage Server because they affect the whole
room. `/ask` uses the exact invoking guild/channel/member identity. Replies disable
all mention expansion, including `@everyone` and replied-user notifications.
Mention replies use the same Agent ingress and identity rules. Interactions and
message IDs are request IDs. Transport never retries an uncertain send.

## Owner control

`/run/user/<uid>/obsidience-discord-bot.sock` is a private Unix stream socket in the
UID-owned mode-0700 runtime directory, itself mode 0600. This filesystem boundary
admits the owner UID (and root); there is no public HTTP/control listener. One
NDJSON request and response per connection, maximum 65,536 bytes including newline,
eight clients, 20-second idle deadline. The exact command schema is:

```text
{"command":"status"}
{"command":"channels"}
{"command":"speech_diagnostics"}
{"command":"wake_calibration","request_id":"FRESH_UUID","member_id":"SNOWFLAKE"}
{"command":"read_wake_calibration","request_id":"DIFFERENT_FRESH_UUID","member_id":"SNOWFLAKE"}
{"command":"join","request_id":"UUID","channel_id":"SNOWFLAKE"}
{"command":"leave","request_id":"UUID"}
{"command":"say","request_id":"UUID","text":"Hello","member_id":"OPTIONAL_SNOWFLAKE"}
{"command":"play","request_id":"UUID","path":"/proc/HARNESS_PID/fd/ADMITTED_FD","file_identity":{"dev":"DECIMAL","ino":"DECIMAL","size":"DECIMAL","mtime_ns":"DECIMAL"},"expires_at_ms":0}
{"command":"cancel_media","request_id":"NEW_UUID","playback_request_id":"ORIGINAL_PLAY_UUID"}
{"command":"pause","request_id":"UUID"}
{"command":"resume","request_id":"UUID"}
{"command":"stop","request_id":"UUID"}
```

`request_id` is mandatory for every effect (8–128 ASCII letters/digits/`_`/`-`).
The most recent 256 effects retain bounded in-memory request fingerprints/receipts.
Same ID and same exact JSON returns its receipt/in-progress status; changed bytes
reject. This cache ends on restart; the Harness retains durable effect receipts and
must never replay an uncertain prior operation after reconnect/restart. A read
status is always safe. Concurrent effects reject as busy; stop/leave preempt.

The two wake-calibration commands are private owner controls, absent from slash
commands and the Agent's capability API. `wake_calibration` requires one current
non-bot member of the joined channel, a ready speech connection, and no active
Agent turn, reply, calibration or diagnostics read. It resets that exact member's
speech stream, then marks only that member's subsequent PCM for a finite ASR
inspection lane. Existing receivers consult the flag on each packet. The worker
collects at most 512 characters, accepts at most ten seconds of PCM, and never
admits an Agent turn from that lane. Other members retain ordinary wake behavior;
the speech owner's existing exclusive-channel admission still applies.

Arming returns immediately and expires after 30 seconds. After the requested
utterance has ended, `read_wake_calibration` returns once within two seconds with
`calibration_probe_text`, or `wake_calibration_unavailable`. Each read requires a
fresh 8–96 character request ID and correlates the worker response to that ID,
the exact member/guild/channel, socket and generation. The read stops additional
probe PCM, consumes the result and resets the exact stream. Its text is never
stored in the generic command replay cache, normal status, ordinary diagnostics,
logs or persistent state. Do not pipe this private response into a journal or
saved file. A lost read result requires a fresh calibration. Stop, leave,
dependency loss, member departure, expiry or an ordinary Agent/reply activation
also clears calibration and resets its stream; following conversation resumes
through the ordinary wake path. Calibration does not alter wake aliases.

Apart from those private calibration controls, commands carrying `member_id` originate in Discord and additionally verify that
the member is currently in the joined voice channel for play/pause/resume/stop/say.
Such joins target the invoker's own current channel and apply its Connect/Speak
permissions; moving the bot or leaving requires Manage Server. Commands without
`member_id` come from the trusted local owner control plane. Bot ingress retains
the exact invoking member; it never inherits the workstation owner's identity.

Only a trusted Harness stop originating inside an active Discord Agent turn may
carry `origin_request_id` from that admitted turn's private context. The transport
verifies the exact active request and member, stops other work/output, and retains
that caller's generation and speech owner so its ordinary reply can complete.
The model cannot select this field. Slash stop and owner stop without an origin
retain the full cancellation/reset semantics below.

`play` accepts only the parent Harness's admitted source descriptor, opens its own
read-only descriptor immediately, confirms it is a regular file, and passes that
held descriptor to FFmpeg as fd 3. It never resolves arbitrary network URLs or
accepts an unvalidated file path. The Harness holds its admitted FD until the
receipt. The transport releases its own FD when playback stops, fails or drains.
The parent includes exact `os.fstat` device/inode/size/mtime-nanosecond values as
decimal strings and a deadline `expires_at_ms = now + 14000`. The transport checks
BigInt fstat on its newly opened descriptor, rejecting a reused FD or changed file,
and rechecks the deadline before starting. It accepts no deadline over 15 seconds
ahead. The parent shields/drains its bounded control request under cancellation,
then releases its admitted descriptor. Internal `cancel_media` names only the
original play request: it stops that exact playback or records a cancellation
that prevents a pending delayed start. It never stops a newer unrelated media
request, never cancels the Agent, and is absent from the Discord slash commands
and model-facing action catalog. Parent cleanup may use it after member departure.
FFmpeg network protocols are disabled. The receipt says
`delivery: audio_playback_started` only after AudioPlayer enters Playing. This
attests local audio packet playback, never a listener's speakers or video playback.
`say` reports only `speech_requested`; playback is observed separately in status.

Spoken replies pause current media and use a separate player. When speech drains,
only the exact retained media generation resumes. Explicit pause cancels automatic
resume. Stop invalidates pending Agent/speech/media work and destroys receive
pipelines, then keeps the channel's wake listener armed for fresh utterances.
Leave additionally destroys the connection and speech socket.

Speech accepts one exact pending request/principal, capped at 4,000 characters.
Oversized explicit `say` rejects; an Agent reply beyond the speech budget becomes
one bounded Unicode-safe reply ending in an ellipsis. Worker errors, speaker
departure and a 120-second delivery deadline cancel only that exact request,
release its audio resources and restore eligible media. Late chunks from completed
or cancelled requests never create a new player. Agent HTTP timeouts also send
the exact authenticated cancellation, rather than merely closing the request.
After speech dependency loss, the next actual Discord speaking event makes one
bounded reconnect attempt; this preserves the generation and replays no old audio
or requests. There is no idle reconnect poll.

## Speech service contract

The existing speech owner exposes `/run/user/<uid>/obsidience-discord-speech.sock`,
mode 0600. One NDJSON connection, same 64KiB limit. No PCM/transcripts are persisted.
Every principal-bound message has `generation` UUID string, `guild_id`, `channel_id`,
`member_id`; generated turns and speech also have `request_id`.

Transport sends `audio` with base64 `pcm`, `sample_rate:16000`, `channels:1`,
`format:"s16le"`; each raw PCM chunk is at most 12,000 bytes. Voice packets are
received with `selfDeaf:false` and decoded per Discord user identity directly to
16k mono through libopus. Each packet reaches speech at its RTC arrival cadence;
there is no receiver-side FFmpeg process or pipe buffering. At most eight live receive pipelines exist. Stream/socket
backpressure terminates that receiver instead of accumulating unbounded audio.
A corrupt Opus packet increments `invalid_opus_packets` and is discarded while
keeping the subscription and decoder alive. The pinned libopus rejects invalid
packets before changing decoder state. Other codec and transport failures remain
failure-visible and close their receiver.

Status includes saturating process-lifetime `receive_counters`: receiver starts,
failures, Opus RX packets, decoded 16k mono PCM bytes, successfully forwarded
16k mono PCM bytes, accepted wake events and accepted transcript events. Values
cap at one billion; they retain no speaker identity, audio or text. Compare
before/after snapshots around one real utterance. `receive_error` and the matching
journal event report only the fixed failing phase, exception class and line
numbers in `bot.mjs`. Exception
messages, raw stack lines, PCM, transcripts and credentials are never emitted.
The speech owner supplies bounded silence for acoustic endpointing between packets.

A global `{"type":"reset","generation":"UUID"}` clears all streams. A principal
`reset` clears one departing user. `cancel` names an exact request. `speak` carries
text and the transcript's same request/principal; local owner `say` additionally
sets `source:"owner"` (default member is the bot itself, with no human followup).

Worker events: `wake`, `transcript` with text, `speech_audio` with 24k mono S16LE
base64 PCM, `speech_end`, `error`. The transport drops stale generations or changed
guild/channel identities. `speech_end` ends the synthesis stream. Only after the
speech AudioPlayer reaches Idle does the transport send exact-principal `played`;
that acknowledgement lets the worker open the invoking member's question followup.
TTS's native 24k mono S16LE PCM is encoded directly with libopus in exact 20 ms
frames (480 samples); no FFmpeg process or intermediate stereo conversion is
used for speech. The Discord AudioPlayer supplies the playback clock. Speech
starts after two of the speech owner's 200 ms chunks (400 ms of queued packets),
or immediately at synthesis EOF for a shorter reply. This bounded prebuffer gives
one chunk of scheduling margin without a timer sleep or altered player stall
threshold. The packet queue is capped at two seconds; a sub-frame PCM remainder
is copied into at most 959 bytes. EOF pads that remainder and drains one silent
codec frame before the normal Discord silence tail. Cancellation destroys the
queue and drops codec state; no old audio is replayed.
Status reports `speech_buffered_ms` and the native player's instantaneous
`speech_player_missed_frames` while playing (`null` otherwise). The latter is
consecutive current misses, not a cumulative underrun counter; a later zero
cannot prove that earlier playback had no gaps.
An Idle transition before `speech_end` cancels the exact request instead of
acknowledging truncated playback as complete.
Playback failures send cancel instead. All packet queues, media FFmpeg and receiver resources close on
leave, dependency loss, stop or teardown.

Transcripts POST once to `http://127.0.0.1:8765/api/discord/turns`, using Bearer
`discord-ingress-token`, with principal/request ID/text and `source:"voice"`.
Text commands use `source:"text"`. Expected result is
`{status:"completed",reply,run_id}`. An unfinished/failed result is never spoken.
Stop POSTs the exact active request to `/api/discord/cancel` and aborts its local
HTTP await; cancellation failures are explicit status, never retry authority.

The owner-only `speech_diagnostics` control command reads the existing speech
socket once for at most eight non-bot members currently in the joined voice
channel. One diagnostic read may be pending, with a two-second total deadline.
Only responses matching the current generation, socket, full principal and current
channel membership are admitted. Stop or speech disconnect ends the pending read.
No reconnect, pipeline creation, microphone, model invocation or periodic polling
is started. Each local-only result includes its member ID and `received`; an absent
response has `received:false`, and `complete:false` marks a partial result.

Response fields are explicitly typed and allowlisted: `available`, received and
terminal PCM frame counts, STT audio/transcription frame counts, VAD start/stop
counts, the fixed possessive/mid-sentence wake rejection counts, input task
completion/failure, runner completion and input queue depth. Counts cap at one
billion. Synthetic probe options/text, PCM and transcripts are never requested,
returned or logged. The command accepts only `command` and optional `request_id`;
it is not a slash command or Agent capability. Worker errors appear in status as
an allowlisted fixed `speech_worker_error` code, without text or identities.

Receive status additionally reports `decoded_pcm_peak`, the largest absolute
signed-16 PCM sample decoded during this process (0–32768), and a saturating
`nonzero_pcm_frames` count of decoded Opus packets containing nonzero samples.
No PCM is retained for these measurements. Read these with the packet/byte
counters to distinguish actual silent input from wake or ASR routing failure.

## Direct verification

`npm run check` validates module syntax. A disposable local import/Opus roundtrip
and FFmpeg PCM resample probe can verify installed bindings without logging in,
joining Discord, sending messages, using the microphone or playing desktop audio.
No automated test suite is included. Actual Discord receive, DAVE, spoken reply,
followup and media acceptance remain a bounded owner-authorized channel check.

## Independent presentation

`/shell/knowledge/?surface=discord` shows only this Agent: accepted Knowledge above
its own Hindsight graph. Its bank is excluded from the Executive's normal Memory
wall and picker, while explicit Agent management can still open it. Public graph
output uses opaque identifiers, accepted Article labels and generic memory types;
actual scoped operations drive highlighting. An empty bank is displayed as empty.
The [local camera producer](camera/README.md) publishes this view as
`Squanchbot Graph` for a normal Discord client to select.

The desktop wake address stays unchanged. The first addressed member owns the
current command and any invited follow-up; other members' audio is discarded
until that ownership ends. Supplied-PCM validation establishes routing, not a
human speaker's acoustic recognition or what listeners hear in Discord.

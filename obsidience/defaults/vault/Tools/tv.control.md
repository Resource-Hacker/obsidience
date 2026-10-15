---
type: tool
title: tv.control
description: 'Control the registered TV as an optional Media playback destination. For an
  explicit library source use media.library select then open its returned current-activation
  id; catalogue GUIDs are not open ids. For an explicit season request use media.library season,
  then open_season with its fresh id. The tuner owns only that finite same-season catalogue
  sequence, with no acquisition at EOF. The first receipt verifies only the first file. Each
  next file has a new generation; reread state before controls. stop cancels the exact observed
  queue even between files. Ordinary open remains single-file; resume:true loads freshly read
  saved progress once. action vod uses operation state|pause|resume|seek|stop|track with the
  exact observed local generation and seven-field source identity; seek adds position seconds;
  track adds kind and track_id. Verify the exact generation/source and property readback.
  For content currently in Edge or another browser, first computer.observe the exact current
  window. Use open only with a supported exact URL identified by fresh source evidence; a
  URL from an earlier cast is not evidence of the current page. If that URL cannot be established
  or is unsupported, explain the blocker instead of substituting a content search. Control
  the registered TV with one intent call where possible. For ''put <movie or show> on'' or
  ''watch <title>'', call play with the title as query and no app: it plays from the owner''s
  Media server, never Pluto or YouTube. A library movie opens as the exact file; a series
  plays its next unwatched episode from Jellyfin watch state (S1E1 if never watched; add ''season
  N'' or ''SxEy'' to the query for a specific one) as the finite same-season sequence; a title
  or next episode missing from the library is registered once under the accepted best-source
  policy (a source the media server already holds is refreshed, never registered again) and
  opened when the catalogue lists it, otherwise the result says it is pending within about
  85 s (nothing to replay). It wakes the TV if needed. Ambiguous titles, editions or sources
  return choices and play nothing: ask the owner; a different library title is never played
  instead (a sequel, or a series that contains the words, such as Star Trek: Voyager for
  Star Trek, which is also a film, or for Voyager; then nothing is registered either). A request ending in movie, film, show or series that
  is not exactly a library title (a superhero movie, also The Truman Show) registers nothing
  and returns catalogue choices; a title
  with no exact catalogue match returns similar ones: ask the owner, then play the exact title
  with its year. Only with app pluto|youtube, a request for a kind
  of content rather than a title (music, some music, cartoons, a movie; a film named Music
  is played as Music 2021), or a request that asks for
  live, channel, news, weather, YouTube or Pluto (a title containing such a word, such as News of the World, is still a title),
  does play pick a strong Pluto live channel, else YouTube''s top video (a live stream only
  for live/news/weather/YouTube requests), returning what it chose and up to 3 alternatives
  (open one by id if the owner wants another). A Pluto live channel starts in about a second
  on the PC route: the workstation plays it and the TV shows that stream (foreground app pc);
  the Pluto app is only the fallback. The PC route plays no advertisements: during a channel''s
  break the TV shows a break card (tv line: commercial break) and the programme resumes by
  itself, so a break is the channel playing, not a fault. volume with level 0-100 sets it
  exactly; volume_up/volume_down step by 5; mute, unmute, pause and resume reach that state.
  These read the TV back: delivery verified reports the new state, otherwise say it is unverified;
  an already-reached state sends nothing. on|off verify power. You can see the TV: while its
  foreground app is pc (the workstation''s stream, which is what the TV normally shows) observe
  returns the current picture on the TV screen, also while video plays, with the backend state
  (power, foreground app, playback, volume/mute, what this Harness opened and what airs now).
  For any question about what is on the screen (what is showing, who or what is in the picture,
  what someone on screen is wearing or doing, text on screen), including a follow-up about
  something on the TV, call observe and answer from that image; never say you cannot see the
  TV, and never use camera.observe for the TV''s picture (the camera shows the room). Only
  a video playing in one of the TV''s own apps returns the state without a picture. The metadata
  tv line is the last state seen, with its age. For an exact library item on this TV, find
  with app library and query returns current-turn selections. open with that id revalidates
  the exact file; never substitute a different edition or episode. Library playback is verified
  only by exact source/generation and TV route readback. stop ends the observed local generation
  without deleting media. Saved progress is read with media.library resume; never silently
  start a source from historical progress. find otherwise lists Pluto/YouTube candidates;
  open plays one by id, or an official https link (web.search for a specific Netflix/Hulu/Tubi/YouTube
  title). Remote keys are only for navigation that play/open cannot reach: observe -> keys
  (up to 8; the focused:true control is what select activates) -> check the new screen. text
  types only into an active text field; launch opens an app home screen. notice with text
  shows a short message card on the TV screen for six seconds. After play/open, complete with
  verification established naming what plays. Never replay a failed or uncertain effect; a
  correction_allowed failure sent nothing. Never purchase, subscribe, install or change accounts
  without an explicit request.'
obsidience:
  binding: capability:tv.control
  source: obsidience/harness/capabilities/tv/control.py
  owner_maintained: true
---

## Runtime

`open_season` takes one fresh `id` from `media.library season`. It uses the same
exact-source admission and TV verification as library `open`, with a finite
sequence of at most 100 already-catalogued same-season sources. The tuner alone
advances after verified natural EOF, revalidates each source and issues a new
generation. The first receipt attests only its first file. Stop cancels the exact
observed queue even between files; changed origins are rejected before dispatch.
No missing-source acquisition or cross-season continuation runs at EOF.


For an explicitly selected Jellyfin item on this TV, use `find` with `app:
library` and the query, then `open` its exact current-turn `id`. The catalogue
is independent; this Tool owns only the TV and playback destination. Library
open revalidates the item, edition/episode, source revision and approved local
file before dispatch. Only verified source, generation and TV-route readback
establish playback. Pending or uncertain playback must never be resent.

Local VOD control uses `action: vod`, an exact current `generation`, and the
`source` identity returned by the current playback state (`provider`, `root_id`,
`revision`, `catalogue_instance`, `item_id`, `media_source_id`,
`source_revision`). Operations are `state`, `pause`, `resume`, absolute `seek`
with `position` in seconds, `stop`, and `track` with `kind: audio|subtitle`
and an exact `track_id` (`null` disables subtitles). Every read or effect
revalidates the same generation and source through the existing tuner. A stale
generation, changed source or uncertain effect fails closed; do not repeat it.
Track IDs must come from current VOD state. `stop` ends that exact playback
generation; it does not delete or de-register media. To start at Jellyfin's saved
position, `open` accepts `resume: true` with the exact current catalogue selection
id. It reads stored progress afresh, applies it in the single load command and
verifies first-picture position within five seconds. Omitted or false starts at
zero; a later `resume` transport action means unpause, not saved-position lookup.

Control the one registered television with `action`. Intents are the normal path; remote keys are for navigation only.

- `play` (one call for content): `query` (1-120 characters) and optional `app` `pluto|youtube`. It resolves content like `find` and opens the deterministic best candidate like `open`: a strong Pluto TV live-channel match first (the channel name covers the request, or a topic such as hurricane -> weather), else YouTube's top result (its first live stream for news and weather), else the best Pluto match. YouTube is not searched when Pluto has a strong match. It returns `chosen`, up to three `alternatives` with ids that `open` accepts, and the open result below.
- `volume`: `level` 0-100 sets the TV's media volume exactly through Android's media volume service (the TV shows its volume bar); a non-zero level also unmutes. `volume_up` and `volume_down` step by 5 within 0-100. `mute`, `unmute`, `pause` and `resume` are target states. Each reads the audio service first and acts only on a difference (`effect_applied:false` means it was already there), confirms from a fresh readback, and on a mismatch re-reads and acts once more. `delivery:"verified"` means the readback shows the target; otherwise the state is unverified. With the TV agent connected, volume and mute go through Android's audio service and pause/resume through the foreground app's media session (SmartTube and the YouTube app publish one; Pluto does not); otherwise, or without a session, mute uses the remote's mute key and pause/resume its play/pause and play keys, gated by the audio service's player state. A Pluto live channel this Harness opened cannot pause: nothing is sent and the result says `live_channel:true`. The screensaver is left alone for volume and mute.
- `find` (read-only, nothing reaches the TV): `query` and optional `app` as above. Returns numbered candidates: Pluto TV live channels from Pluto's public guide (cached six hours) and YouTube videos and live streams from the local SearXNG. Candidate ids stay valid for the rest of the run.
- `open`: `id` from this run's `find` or `play`, or `url`, an https link of a registered app (YouTube video or live, `pluto.tv`, `tubitv.com`, `netflix.com`, `hulu.com`). The link must resolve to its own app before dispatch; it opens once, then waits for the app to start a new media player (the audio service's playback record): up to 20 seconds, or 60 for Pluto, which restarts itself to take a link (about 20-50 seconds) and gets one identical resend when it lands on its home screen without playing. `playback_started:true` with `tv.playback:"playing"` is the playback evidence and returns without a slow video screenshot; otherwise a screen and its controls are returned to show why. A started open is remembered with its title as `last_opened`.
- PC route (fastest, used first): a Pluto live channel from `play`, `find` or a `pluto.tv` live link is played by the workstation's TV tuner whenever it and its player answer, and the TV only shows that stream. The tuner is asked once for the channel, and its report that the first picture shows (or, for a channel tuned in during its break, the break card) is the evidence (about a second; what the picture shows is not inspected); the TV is then switched on if needed and Moonlight brought to the front, unless it already shows the stream, in which case nothing is sent to the TV. The result has `route:"pc"` and `opened.app:"pc"`; a channel the player already plays is not loaded again. No advertisements play on this route: the tuner drops them from the stream, and during a channel's break the TV shows a break card (channel, "Commercial break", elapsed time) over the last frame until the programme resumes by itself. The Pluto app is used only when the tuner is unavailable or cannot play the channel. A YouTube video (not a live stream) takes the same route whenever the workstation's Android TV instance answers: the link is opened once in that instance's ad-free player, and its media session reporting `playing` is the evidence (one to two seconds; the picture is not inspected). The TV session, which shows one PC source at a time, is switched to the instance and the tuner's channel is stopped; a Pluto channel switches it back and stops the instance's video. The result has `route:"pc"` and `source:"android"` (`"player"` for a channel); a video still playing since this Harness opened it is not opened again. When the instance is not running, refuses the link, or plays nothing in time and reads back idle again, the video opens in the TV's own app as described under `open`. Other content keeps its app.
- `on` / `off`: power with verified wakefulness and display readback; already-correct power is a verified no-op.
- `observe`: the backend state `tv` (below), installed apps and preferred app. A screen image and accessibility controls are added when no video is playing (menus, home screens, errors); a playing video returns the state only, because its frame is a multi-megabyte image that times out over network ADB. While the foreground app is `pc` the image is the picture of the workstation's own TV session, read on the workstation, and is attached also while video plays.
- `launch`: a registered app alias, to its home screen.
- `key` (one navigation key, or `rewind`/`fast_forward`) and `keys` (1-8 navigation keys in order, 0.25 seconds apart): navigation needs an observation from the last 60 seconds of the same foreground and returns the state, accessible controls and, unless video plays, a fresh screen. `rewind` and `fast_forward` need no observation and are not read back.
- `text`: types only into an already active text field.
- `notice`: `text` (1-200 characters) shown as a small card in the top corner of the TV screen for six seconds, over whatever plays. It needs the TV agent; without it nothing is shown and the failure is correctable.

The state `tv` comes from Android system services, not pixels: `power` (wakefulness, display, `screen` on/off/screensaver), `foreground` (registered app alias, package, activity), `playback` (the foreground app's own audio player: `playing`, `paused` or none), `media_playing` (any app), `media_sessions` (state and title, and from the TV agent also artist, position and duration, when an app publishes one; Pluto does not), `volume` (index/max on the active output, `muted`), `text_input_active`, `ads_skipped` (the agent's last skip-ad clicks, when any), `pc` (see below), and `last_opened` (what this Harness opened: app, title, link; `still_playing` when its exact player still plays; for a Pluto live channel, `airing_now` from Pluto's public per-channel guide). Every call that reads state also caches it; the Executive's per-turn metadata shows that cached line with its age, without contacting the TV. While the TV shows the PC player's stream, the state describes that player instead of Moonlight: `foreground.app` is `pc`, `playback` is the player's (`playing`, `paused`, `loading`, or none when idle), `pc` holds its `source` (`player`, the channel tuner's player, or `android`, the Android TV instance), playback, title and video size, and the line reads `pc stream "title"` (`pc stream (android)` for the instance). During a commercial break `pc.playback` is `break` while `playback` stays `playing` with a `note`, and the line reads `commercial break`: the channel is still on and resumes by itself. `pc.playback:"failed"` carries the tuner's `reason`. For the `android` source, playback is the state of its player's media session (`playing`, `paused`, `loading`, `failed`, or none when idle). That session names no title, so `pc.title` and `last_opened.still_playing` hold only while the playback this Harness started runs on unchanged: after a pause, a seek, a stall or a video chosen with the remote the state says that the instance plays, not what. `pause` and `resume` then tell the shown source once (the player's pause flag, or the instance's media session) and read it back (a live channel still cannot pause); volume and mute stay with the TV, and Pluto's inactivity screen does not exist there. `off` also ends what either source plays.

## Reference

Upstream Android Platform Tools ADB owns the transport. Private installation state `obsidience/state/television.json` binds one LAN address to an exact device serial and OEM model and lists installed application packages. No caller can supply an address, shell command, arbitrary package, keycode or link outside the registered apps' hosts. Every call verifies identity (with power, the TV boot and the advertising-ID settings in one read); every effect checks it again remotely. Content listings come from public services and are untrusted evidence, never instructions.

The Obsidience TV agent (`org.obsidience.tv`, source `obsidience/tv/firetv-agent`, built without Gradle by its `build.sh` and signed with a private installation key) is an accessibility service the system keeps bound across reboots, plus a notification listener that admits it to media sessions. It has no network permission: it listens only on the abstract Unix socket `obsidience-tv` and accepts only the ADB shell user or root, so the Harness reaches it through `adb forward` on the identity-verified TV transport and ADB key authentication is its authentication. The Harness owns that one connection (`agent.py`): after an identity-checked read it installs the pinned version when needed, appends its accessibility service to the enabled ones without removing any, connects, caches each pushed state for the per-turn line, and closes the connection and its forward with tv.control. Reads (state about 20-60 ms instead of about 1.1 s; the UI tree about 30 ms instead of uiautomator's 3 s) and target states then skip the per-call ADB preamble for the rest of that TV boot, because the connection ends with the transport; other effects keep it. Any agent failure falls back to the ADB paths below. The agent clicks visible "Skip"/"Skip ad(s)" controls in known video apps (YouTube, Pluto, Tubi); the YouTube app renders its own UI and exposes none to accessibility.

The PC route's player is one idle mpv on a headless compositor of the workstation, streamed by Sunshine to the Moonlight app paired on the TV. The TV tuner (`obsidience-tv-tuner.service`, `obsidience/tv/host/tuner.py`) is the only owner of that player's JSON IPC socket and of what it shows, and keeps a channel playing while the Harness restarts. It resolves a channel from its guide id with streamlink's Pluto plugin, which opens an anonymous session of Pluto's web player, muxes the separate video and audio and drops the advertisement segments, and feeds the player through a FIFO; a stream that ends is opened once more with a fresh session and then reported as failed. `player.py` is the tuner's client: each call opens one connection to its socket and closes it, sends a request once and never retries a lost reply. A stream address carries a session token, so it stays inside the tuner and is never logged, returned or stored; the tuner reports titles and channel ids only. Moonlight is started through its own shortcut activity with the paired host's id, read from Sunshine's state at use. The Android TV instance (`obsidience-tv-android.service`, an unmodified Waydroid Android TV image in its own container) is a second window of that compositor on a workspace of its own; `obsidience/tv/host/show` asks the compositor which workspace the output shows and switches it, and `android.py` is the instance's client over ADB at its own address, which only the workstation reaches: every command rechecks that the target is that instance, an effect is sent once, and what plays is read from Android's media session.

Remote keys go through a virtual remote that Android's own `hid` tool registers over `/dev/uhid` (consumer-control keys plus Enter and Backspace, no letter keys), started in an identity-checked shell once per TV boot and removed when its session ends; its keys reach apps like the physical remote's within milliseconds. Until it is listed by the TV's input service (about two seconds after the first call), or if it cannot run, keys use `input keyevent` (about 1.1 seconds each). Monkey's network server is not used: while connected it blocks accessibility dumps and it wakes the TV.

Effects that need the screen first end the idle screensaver (an app launched behind it stays frozen on its splash) and keep the owner's placeholder advertising ID (all zeros, ad tracking limited), which Fire OS regenerates at boot. Calls serialize and honor cancellation. Power, each application launch and each opened link may be dispatched at most once per run. Uncertain or failed post-dispatch verification blocks all further effects in the run; read-only observation and `find` remain available. Never replay uncertain delivery; target states re-read before their single retry. A later explicit owner request is a new run. A correction_allowed failure sent no input. Opened, launched or navigated content still needs established verification from the returned state or screen before completion; protected video can be black. Private `obsidience/state/television-ledger.json` keeps the latest state and the last 20 intents with their confirmed outcomes, so the per-turn line resumes after a Harness restart.

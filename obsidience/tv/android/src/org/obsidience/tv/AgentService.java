package org.obsidience.tv;

import android.accessibilityservice.AccessibilityService;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.GradientDrawable;
import android.hardware.display.DisplayManager;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.AudioPlaybackConfiguration;
import android.media.MediaMetadata;
import android.media.session.MediaController;
import android.media.session.MediaSessionManager;
import android.media.session.PlaybackState;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;
import android.util.TypedValue;
import android.view.Display;
import android.view.Gravity;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Obsidience's TV agent. The system keeps an enabled accessibility service bound
 * (and rebinds it after reboot), so this service hosts everything: the socket
 * server, foreground tracking, the UI tree, media sessions, volume, on-screen
 * notices and the skip-ad watch. All state is owned by the main thread.
 */
public class AgentService extends AccessibilityService {
    static final String TAG = "ObsidienceTv";
    static final int VERSION = 1;
    static volatile AgentService instance;

    /** Visible labels of skip-ad controls: "Skip", "Skip ad", "Skip Ads ›". */
    private static final Pattern SKIP = Pattern.compile(
            "\\s*skip(\\s+ads?)?\\s*[\\u203a>\\u25b6\\u23ed|]*\\s*", Pattern.CASE_INSENSITIVE);
    /** Video apps whose skip-ad controls are clicked; a "Skip" elsewhere (setup flows) is never touched. */
    private static final List<String> SKIP_PACKAGES = Arrays.asList(
            "com.amazon.firetv.youtube", "com.amazon.firetv.youtube.tv", "com.google.android.youtube.tv",
            "tv.pluto.android", "com.tubitv.ott");
    private static final Pattern PLAYER = Pattern.compile("piid:(\\d+) .*? state:(\\w+)");
    private static final String[] SESSION_STATES = {"none", "stopped", "paused", "playing", "fast_forwarding",
            "rewinding", "buffering", "error", "connecting", "skipping_to_previous", "skipping_to_next",
            "skipping_to_queue_item"};
    private static final int MUSIC = AudioManager.STREAM_MUSIC;

    final Handler main = new Handler(Looper.getMainLooper());
    private Server server;
    private AudioManager audio;
    private PowerManager power;
    private DisplayManager displays;
    private MediaSessionManager media;
    private WindowManager windows;
    private ComponentName listener;
    private boolean started;

    private String fgPackage = "";
    private String fgActivity = "";
    private boolean dreaming;
    private final Map<String, Boolean> activities = new HashMap<>();

    private final List<MediaController> controllers = new ArrayList<>();
    private final Map<MediaController, MediaController.Callback> callbacks = new HashMap<>();
    private boolean sessionsWatched;
    private final MediaSessionManager.OnActiveSessionsChangedListener sessionsListener = this::onSessions;

    private int lastAudible = -1;
    private String pushed = "";

    private boolean skipAds = true;
    private final Set<String> skipPackages = new HashSet<>(SKIP_PACKAGES);
    private boolean skipScheduled;
    private long lastScan;
    private String lastSkipKey = "";
    private long lastSkipAt;
    private final ArrayDeque<JSONObject> skips = new ArrayDeque<>();

    private int treeGeneration;
    private final List<AccessibilityNodeInfo> handles = new ArrayList<>();

    private TextView notice;

    // ---- lifecycle ------------------------------------------------------------------------

    @Override protected void onServiceConnected() {
        if (started) return;
        started = true;
        instance = this;
        audio = getSystemService(AudioManager.class);
        power = getSystemService(PowerManager.class);
        displays = getSystemService(DisplayManager.class);
        media = getSystemService(MediaSessionManager.class);
        windows = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
        listener = new ComponentName(this, MediaListener.class);
        IntentFilter filter = new IntentFilter();
        filter.addAction("android.media.VOLUME_CHANGED_ACTION");
        filter.addAction("android.media.STREAM_MUTE_CHANGED_ACTION");
        filter.addAction(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        filter.addAction(Intent.ACTION_DREAMING_STARTED);
        filter.addAction(Intent.ACTION_DREAMING_STOPPED);
        registerReceiver(receiver, filter, null, main);
        audio.registerAudioPlaybackCallback(players, main);
        watchSessions();
        server = new Server(main, this::handle);
        try {
            server.start();
        } catch (IOException e) {
            Log.e(TAG, "socket " + Server.NAME + " unavailable", e);
        }
        Log.i(TAG, "agent " + VERSION + " started");
    }

    @Override public boolean onUnbind(Intent intent) {
        stop();
        return super.onUnbind(intent);
    }

    @Override public void onDestroy() {
        stop();
        super.onDestroy();
    }

    @Override public void onInterrupt() { }

    /** Release everything acquired in onServiceConnected; safe to call twice. */
    private void stop() {
        if (!started) return;
        started = false;
        if (instance == this) instance = null;
        if (server != null) server.close();
        try { unregisterReceiver(receiver); } catch (IllegalArgumentException ignored) { }
        audio.unregisterAudioPlaybackCallback(players);
        if (sessionsWatched) media.removeOnActiveSessionsChangedListener(sessionsListener);
        setControllers(new ArrayList<>());
        hideNotice();
        main.removeCallbacksAndMessages(null);
        Log.i(TAG, "agent stopped");
    }

    // ---- events ---------------------------------------------------------------------------

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        CharSequence pkg = event.getPackageName();
        if (pkg == null) return;
        int type = event.getEventType();
        if (type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            CharSequence cls = event.getClassName();
            if (cls != null && isActivity(pkg.toString(), cls.toString())) {
                fgPackage = pkg.toString();
                fgActivity = cls.toString();
                dreaming = fgActivity.endsWith("DreamActivity");
            }
            changed();
        } else if (type == AccessibilityEvent.TYPE_WINDOWS_CHANGED) {
            changed();
        }
        if (skipAds && skipPackages.contains(pkg.toString())) scheduleSkipScan();
    }

    private boolean isActivity(String pkg, String cls) {
        if (cls.endsWith("DreamActivity")) return true;  // The framework hosts dreams; no manifest entry.
        String key = pkg + "/" + cls;
        Boolean known = activities.get(key);
        if (known == null) {
            try {
                getPackageManager().getActivityInfo(new ComponentName(pkg, cls), 0);
                known = true;
            } catch (PackageManager.NameNotFoundException e) {
                known = false;
            }
            if (activities.size() > 512) activities.clear();
            activities.put(key, known);
        }
        return known;
    }

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            String action = String.valueOf(intent.getAction());
            if (Intent.ACTION_DREAMING_STARTED.equals(action)) dreaming = true;
            else if (Intent.ACTION_DREAMING_STOPPED.equals(action)) dreaming = false;
            if (action.contains("VOLUME") && intent.getIntExtra("android.media.EXTRA_VOLUME_STREAM_TYPE", MUSIC) != MUSIC) return;
            changed();
        }
    };

    private final AudioManager.AudioPlaybackCallback players = new AudioManager.AudioPlaybackCallback() {
        @Override public void onPlaybackConfigChanged(List<AudioPlaybackConfiguration> configs) {
            changed();
        }
    };

    /** Called when the notification listener connects: getActiveSessions now admits this app. */
    void watchSessions() {
        if (sessionsWatched || media == null) return;
        try {
            media.addOnActiveSessionsChangedListener(sessionsListener, listener, main);
            sessionsWatched = true;
            onSessions(media.getActiveSessions(listener));
        } catch (SecurityException e) {
            Log.i(TAG, "media sessions wait for the notification listener");
        }
    }

    private void onSessions(List<MediaController> list) {
        setControllers(list == null ? new ArrayList<>() : new ArrayList<>(list));
        changed();
    }

    private void setControllers(List<MediaController> list) {
        for (Map.Entry<MediaController, MediaController.Callback> entry : callbacks.entrySet()) {
            entry.getKey().unregisterCallback(entry.getValue());
        }
        callbacks.clear();
        controllers.clear();
        controllers.addAll(list);
        for (MediaController controller : controllers) {
            MediaController.Callback callback = new MediaController.Callback() {
                @Override public void onPlaybackStateChanged(PlaybackState state) { changed(); }
                @Override public void onMetadataChanged(MediaMetadata metadata) { changed(); }
                @Override public void onSessionDestroyed() { changed(); }
            };
            controller.registerCallback(callback, main);
            callbacks.put(controller, callback);
        }
    }

    private final Runnable pushState = () -> {
        if (server == null || !server.hasClients()) return;
        try {
            JSONObject state = state();
            // Positions and the capture time change constantly; only meaningful changes are pushed.
            JSONObject key = new JSONObject(state.toString());
            key.remove("at");
            JSONArray sessions = key.getJSONArray("sessions");
            for (int i = 0; i < sessions.length(); i++) sessions.getJSONObject(i).remove("position_ms");
            String signature = key.toString();
            if (signature.equals(pushed)) return;
            pushed = signature;
            server.broadcast(new JSONObject().put("event", "state").put("state", state));
        } catch (Exception e) {
            Log.w(TAG, "state push failed", e);
        }
    };

    /** Coalesce bursts of changes into one state push. */
    private void changed() {
        main.removeCallbacks(pushState);
        main.postDelayed(pushState, 150);
    }

    // ---- requests -------------------------------------------------------------------------

    static JSONObject error(Object id, String message) {
        try {
            return new JSONObject().put("id", id == null ? JSONObject.NULL : id).put("ok", false).put("error", message);
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /** One request, on the main thread. */
    JSONObject handle(JSONObject request) {
        Object id = request.opt("id");
        try {
            JSONObject result;
            switch (request.optString("op")) {
                case "hello":
                    result = new JSONObject().put("version", VERSION).put("sdk", Build.VERSION.SDK_INT)
                            .put("uptime_ms", SystemClock.elapsedRealtime());
                    break;
                case "state": result = state(); break;
                case "tree": result = tree(request.optInt("max", 400)); break;
                case "click": result = click(request.getString("handle")); break;
                case "global": result = global(request.getString("action")); break;
                case "volume": result = volume(request); break;
                case "transport": result = transport(request); break;
                case "notice": result = notice(request.getString("text"), request.optInt("ms", 4000)); break;
                case "config": result = config(request); break;
                default: return error(id, "unknown op");
            }
            return result.put("id", id == null ? JSONObject.NULL : id).put("ok", true);
        } catch (Exception e) {
            return error(id, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    JSONObject state() throws JSONException {
        JSONObject state = new JSONObject().put("at", System.currentTimeMillis()).put("version", VERSION);
        AccessibilityWindowInfo active = null;
        boolean ime = false;
        for (AccessibilityWindowInfo window : getWindows()) {
            if (window.isActive()) active = window;
            if (window.getType() == AccessibilityWindowInfo.TYPE_INPUT_METHOD) ime = true;
        }
        String pkg = fgPackage;
        int windowId = -1;
        if (active != null) {
            windowId = active.getId();
            AccessibilityNodeInfo root = active.getRoot();
            if (root != null && root.getPackageName() != null) pkg = root.getPackageName().toString();
        }
        state.put("foreground", new JSONObject().put("package", pkg)
                .put("activity", pkg.equals(fgPackage) ? fgActivity : "").put("window", windowId));
        state.put("ime", ime);
        state.put("power", powerState());
        state.put("volume", volumeState());
        JSONArray players = players();
        state.put("players", players).put("media_playing", anyStarted(players));
        if (!sessionsWatched) watchSessions();
        JSONArray sessions = new JSONArray();
        for (MediaController controller : controllers) sessions.put(session(controller));
        state.put("sessions", sessions);
        synchronized (skips) { state.put("ads_skipped", new JSONArray(skips)); }
        state.put("config", configState());
        return state;
    }

    /** Media players with their state; toString() is the only public view of it, and uids are anonymized for apps. */
    private JSONArray players() throws JSONException {
        JSONArray players = new JSONArray();
        for (AudioPlaybackConfiguration config : audio.getActivePlaybackConfigurations()) {
            if (config.getAudioAttributes().getUsage() != AudioAttributes.USAGE_MEDIA) continue;
            Matcher match = PLAYER.matcher(config.toString());
            if (match.find()) {
                players.put(new JSONObject().put("piid", Integer.parseInt(match.group(1))).put("state", match.group(2)));
            }
        }
        return players;
    }

    private static boolean anyStarted(JSONArray players) {
        for (int i = 0; i < players.length(); i++) {
            if ("started".equals(players.optJSONObject(i).optString("state"))) return true;
        }
        return false;
    }

    private JSONObject powerState() throws JSONException {
        Display display = displays.getDisplay(Display.DEFAULT_DISPLAY);
        int code = display == null ? Display.STATE_UNKNOWN : display.getState();
        String[] names = {"UNKNOWN", "OFF", "ON", "DOZE", "DOZE_SUSPEND", "VR", "ON_SUSPEND"};
        return new JSONObject().put("interactive", power.isInteractive())
                .put("dreaming", dreaming)
                .put("display", code >= 0 && code < names.length ? names[code] : String.valueOf(code));
    }

    private JSONObject volumeState() throws JSONException {
        boolean muted = audio.isStreamMute(MUSIC);
        // getStreamVolume reads 0 while muted; the audible index is what dumpsys reports.
        int index = muted ? lastAudibleIndex() : audio.getStreamVolume(MUSIC);
        if (!muted) lastAudible = index;
        return new JSONObject().put("index", index).put("max", audio.getStreamMaxVolume(MUSIC))
                .put("muted", muted).put("device", outputDevice());
    }

    private int lastAudibleIndex() {
        try {
            return (Integer) AudioManager.class.getMethod("getLastAudibleStreamVolume", int.class).invoke(audio, MUSIC);
        } catch (Exception e) {
            return lastAudible;
        }
    }

    private String outputDevice() {
        try {
            int devices = (Integer) AudioManager.class.getMethod("getDevicesForStream", int.class).invoke(audio, MUSIC);
            int[] bits = {0x2, 0x400, 0x40000, 0x80, 0x100, 0x200, 0x4, 0x8, 0x4000000, 0x20000};
            String[] names = {"speaker", "hdmi", "hdmi_arc", "bt_a2dp", "bt_a2dp_hp", "bt_a2dp_spk", "headset",
                    "headphone", "usb_headset", "line"};
            for (int i = 0; i < bits.length; i++) if ((devices & bits[i]) != 0) return names[i];
            return Integer.toHexString(devices);
        } catch (Exception e) {
            return "";
        }
    }

    private JSONObject session(MediaController controller) throws JSONException {
        JSONObject row = new JSONObject().put("package", controller.getPackageName()).put("active", true);
        PlaybackState playback = controller.getPlaybackState();
        if (playback != null) {
            int code = playback.getState();
            row.put("state", code >= 0 && code < SESSION_STATES.length ? SESSION_STATES[code] : String.valueOf(code));
            long position = playback.getPosition();
            if (code == PlaybackState.STATE_PLAYING && playback.getLastPositionUpdateTime() > 0) {
                position += (long) ((SystemClock.elapsedRealtime() - playback.getLastPositionUpdateTime())
                        * playback.getPlaybackSpeed());
            }
            row.put("position_ms", Math.max(0, position)).put("actions", playback.getActions());
        }
        MediaMetadata metadata = controller.getMetadata();
        if (metadata != null) {
            String title = metadata.getString(MediaMetadata.METADATA_KEY_TITLE);
            if (title == null && metadata.getDescription().getTitle() != null) {
                title = metadata.getDescription().getTitle().toString();
            }
            String artist = metadata.getString(MediaMetadata.METADATA_KEY_ARTIST);
            if (artist == null && metadata.getDescription().getSubtitle() != null) {
                artist = metadata.getDescription().getSubtitle().toString();
            }
            if (title != null) row.put("title", clip(title, 160));
            if (artist != null) row.put("artist", clip(artist, 160));
            long duration = metadata.getLong(MediaMetadata.METADATA_KEY_DURATION);
            if (duration > 0) row.put("duration_ms", duration);
        }
        return row;
    }

    private JSONObject tree(int max) throws JSONException {
        max = Math.max(1, Math.min(max, 1500));
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) throw new IllegalStateException("no active window");
        treeGeneration++;
        handles.clear();
        JSONArray nodes = new JSONArray();
        ArrayDeque<Object[]> stack = new ArrayDeque<>();
        stack.push(new Object[]{root, 0});
        boolean truncated = false;
        Rect bounds = new Rect();
        while (!stack.isEmpty()) {
            Object[] item = stack.pop();
            AccessibilityNodeInfo node = (AccessibilityNodeInfo) item[0];
            int depth = (Integer) item[1];
            for (int i = node.getChildCount() - 1; i >= 0; i--) {
                AccessibilityNodeInfo child = node.getChild(i);
                if (child != null) stack.push(new Object[]{child, depth + 1});
            }
            String text = node.isPassword() || node.getText() == null ? "" : clip(node.getText().toString(), 160);
            String desc = node.getContentDescription() == null ? "" : clip(node.getContentDescription().toString(), 160);
            String id = node.getViewIdResourceName() == null ? "" : node.getViewIdResourceName();
            if (text.isEmpty() && desc.isEmpty() && id.isEmpty() && !node.isClickable() && !node.isFocusable()
                    && !node.isFocused() && !node.isSelected()) continue;
            if (nodes.length() >= max) { truncated = true; break; }
            node.getBoundsInScreen(bounds);
            JSONObject row = new JSONObject().put("h", treeGeneration + "." + handles.size()).put("d", depth);
            handles.add(node);
            CharSequence cls = node.getClassName();
            if (cls != null) row.put("cls", cls.toString().substring(cls.toString().lastIndexOf('.') + 1));
            if (!text.isEmpty()) row.put("text", text);
            if (!desc.isEmpty()) row.put("desc", desc);
            if (!id.isEmpty()) row.put("id", clip(id, 160));
            row.put("b", new JSONArray().put(bounds.left).put(bounds.top).put(bounds.right).put(bounds.bottom));
            if (node.isFocused()) row.put("focused", true);
            if (node.isClickable()) row.put("clickable", true);
            if (node.isFocusable()) row.put("focusable", true);
            if (node.isSelected()) row.put("selected", true);
            if (node.isPassword()) row.put("password", true);
            if (!node.isVisibleToUser()) row.put("hidden", true);
            nodes.put(row);
        }
        CharSequence pkg = root.getPackageName();
        return new JSONObject().put("package", pkg == null ? "" : pkg.toString()).put("window", root.getWindowId())
                .put("activity", pkg != null && pkg.toString().equals(fgPackage) ? fgActivity : "")
                .put("nodes", nodes).put("truncated", truncated);
    }

    private JSONObject click(String handle) throws JSONException {
        String[] parts = handle.split("\\.");
        int index = parts.length == 2 && parts[0].equals(String.valueOf(treeGeneration)) ? Integer.parseInt(parts[1]) : -1;
        if (index < 0 || index >= handles.size()) throw new IllegalArgumentException("stale handle; read the tree again");
        AccessibilityNodeInfo node = handles.get(index);
        if (!node.refresh()) throw new IllegalStateException("node is gone; read the tree again");
        AccessibilityNodeInfo target = clickable(node);
        boolean clicked = target.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        return new JSONObject().put("clicked", clicked).put("ancestor", target != node);
    }

    /** The node or its nearest clickable ancestor (labels usually sit inside the clickable row). */
    private static AccessibilityNodeInfo clickable(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo current = node;
        for (int i = 0; current != null && i < 6; i++) {
            if (current.isClickable()) return current;
            current = current.getParent();
        }
        return node;
    }

    private JSONObject global(String action) throws JSONException {
        int code;
        if ("back".equals(action)) code = GLOBAL_ACTION_BACK;
        else if ("home".equals(action)) code = GLOBAL_ACTION_HOME;
        else throw new IllegalArgumentException("global action is back or home");
        return new JSONObject().put("performed", performGlobalAction(code));
    }

    private JSONObject volume(JSONObject request) throws JSONException {
        int flags = request.optBoolean("show", true) ? AudioManager.FLAG_SHOW_UI : 0;
        if (request.has("level")) {
            int level = request.getInt("level");
            if (level < 0 || level > audio.getStreamMaxVolume(MUSIC)) throw new IllegalArgumentException("level out of range");
            audio.setStreamVolume(MUSIC, level, flags);
        }
        if (request.has("mute")) {
            audio.adjustStreamVolume(MUSIC, request.getBoolean("mute") ? AudioManager.ADJUST_MUTE
                    : AudioManager.ADJUST_UNMUTE, flags);
        }
        return new JSONObject().put("volume", volumeState()).put("media_playing", anyStarted(players()));
    }

    private JSONObject transport(JSONObject request) throws JSONException {
        String pkg = request.optString("package");
        MediaController target = null;
        for (MediaController controller : controllers) {
            if (pkg.isEmpty() ? target == null : controller.getPackageName().equals(pkg)) target = controller;
        }
        if (target == null) throw new IllegalStateException("no media session" + (pkg.isEmpty() ? "" : " for " + pkg));
        JSONObject before = session(target);
        MediaController.TransportControls controls = target.getTransportControls();
        switch (request.getString("action")) {
            case "play": controls.play(); break;
            case "pause": controls.pause(); break;
            case "stop": controls.stop(); break;
            case "next": controls.skipToNext(); break;
            case "previous": controls.skipToPrevious(); break;
            case "seek": controls.seekTo(Math.max(0, request.getLong("position_ms"))); break;
            default: throw new IllegalArgumentException("transport action is play, pause, stop, next, previous or seek");
        }
        return new JSONObject().put("package", target.getPackageName()).put("before", before);
    }

    // ---- notice overlay -------------------------------------------------------------------

    private final Runnable hide = this::hideNotice;

    private JSONObject notice(String text, int ms) throws JSONException {
        hideNotice();
        TextView view = new TextView(this);
        view.setText(clip(text, 200));
        view.setTextColor(0xFFFFFFFF);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        view.setMaxWidth(getResources().getDisplayMetrics().widthPixels / 3);
        int pad = (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 16, getResources().getDisplayMetrics());
        view.setPadding(pad * 3 / 2, pad, pad * 3 / 2, pad);
        GradientDrawable background = new GradientDrawable();
        background.setColor(0xE6181A20);
        background.setCornerRadius(pad);
        view.setBackground(background);
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.END;
        params.x = pad * 3;
        params.y = pad * 3;
        windows.addView(view, params);
        notice = view;
        int shown = Math.max(1000, Math.min(ms, 15000));
        main.postDelayed(hide, shown);
        return new JSONObject().put("shown_ms", shown);
    }

    private void hideNotice() {
        main.removeCallbacks(hide);
        if (notice != null) {
            try { windows.removeView(notice); } catch (IllegalArgumentException ignored) { }
            notice = null;
        }
    }

    // ---- skip-ad watch --------------------------------------------------------------------

    private final Runnable skipScan = () -> {
        skipScheduled = false;
        lastScan = SystemClock.uptimeMillis();
        try {
            scanSkip();
        } catch (RuntimeException e) {
            Log.w(TAG, "skip scan failed", e);
        }
    };

    private void scheduleSkipScan() {
        if (skipScheduled) return;
        skipScheduled = true;
        // Content changes arrive several times a second during playback; scan at most every 0.6 s.
        long wait = Math.max(250, 600 - (SystemClock.uptimeMillis() - lastScan));
        main.postDelayed(skipScan, wait);
    }

    private void scanSkip() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null || root.getPackageName() == null) return;
        String pkg = root.getPackageName().toString();
        if (!skipAds || !skipPackages.contains(pkg)) return;
        for (AccessibilityNodeInfo node : root.findAccessibilityNodeInfosByText("skip")) {
            String label = node.getText() != null ? node.getText().toString()
                    : node.getContentDescription() != null ? node.getContentDescription().toString() : "";
            if (!SKIP.matcher(label).matches() || !node.isVisibleToUser()) continue;
            AccessibilityNodeInfo target = clickable(node);
            Rect bounds = new Rect();
            target.getBoundsInScreen(bounds);
            String key = pkg + bounds.flattenToString();
            long now = SystemClock.uptimeMillis();
            if (key.equals(lastSkipKey) && now - lastSkipAt < 3000) return;
            lastSkipKey = key;
            lastSkipAt = now;
            boolean clicked = target.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            Log.i(TAG, "skip-ad control '" + label + "' in " + pkg + " clicked=" + clicked);
            try {
                JSONObject event = new JSONObject().put("at", System.currentTimeMillis()).put("package", pkg)
                        .put("label", clip(label, 60)).put("clicked", clicked);
                synchronized (skips) {
                    skips.addLast(event);
                    while (skips.size() > 5) skips.removeFirst();
                }
                if (server != null) server.broadcast(new JSONObject(event.toString()).put("event", "ad_skipped"));
            } catch (JSONException ignored) { }
            return;
        }
    }

    // ---- config ---------------------------------------------------------------------------

    private JSONObject config(JSONObject request) throws JSONException {
        if (request.has("skip_ads")) skipAds = request.getBoolean("skip_ads");
        if (request.has("skip_packages")) {
            JSONArray list = request.getJSONArray("skip_packages");
            if (list.length() > 30) throw new IllegalArgumentException("at most 30 packages");
            skipPackages.clear();
            for (int i = 0; i < list.length(); i++) skipPackages.add(list.getString(i));
        }
        return new JSONObject().put("config", configState());
    }

    private JSONObject configState() throws JSONException {
        return new JSONObject().put("skip_ads", skipAds).put("skip_packages", new JSONArray(skipPackages));
    }

    private static String clip(String text, int limit) {
        return text.length() <= limit ? text : text.substring(0, limit);
    }
}

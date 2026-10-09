package org.obsidience.tv;

import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.Handler;
import android.system.Os;
import android.system.OsConstants;
import android.util.Log;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The agent's only channel: an abstract Unix socket that ADB forwards to
 * (`adb forward tcp:N localabstract:obsidience-tv`). adbd connects as the shell
 * user, so ADB's key authentication is the authentication; any other peer uid
 * except root is refused. Newline-delimited JSON: each request line is answered
 * with one line carrying its id; state changes are pushed as {event: ...} lines.
 *
 * Requests are handled on the service's main thread (one owner of its state);
 * socket writes go through one writer thread so the main thread never blocks.
 */
final class Server implements Runnable {
    static final String NAME = "obsidience-tv";
    private static final int MAX_LINE = 64 * 1024;
    private static final int MAX_CLIENTS = 4;

    interface Requests { JSONObject handle(JSONObject request); }

    private final Handler main;
    private final Requests handler;
    private final ExecutorService writer = Executors.newSingleThreadExecutor();
    private final CopyOnWriteArrayList<Client> clients = new CopyOnWriteArrayList<>();
    private LocalServerSocket socket;
    private volatile boolean closed;

    Server(Handler main, Requests handler) {
        this.main = main;
        this.handler = handler;
    }

    void start() throws IOException {
        socket = new LocalServerSocket(NAME);
        Thread thread = new Thread(this, "obsidience-tv-accept");
        thread.setDaemon(true);
        thread.start();
    }

    boolean hasClients() { return !clients.isEmpty(); }

    @Override public void run() {
        while (!closed) {
            LocalSocket peer;
            try {
                peer = socket.accept();
            } catch (IOException e) {
                if (!closed) Log.w(AgentService.TAG, "accept failed", e);
                return;
            }
            int uid;
            try {
                uid = peer.getPeerCredentials().getUid();
            } catch (IOException e) {
                uid = -1;
            }
            if ((uid != 2000 && uid != 0) || clients.size() >= MAX_CLIENTS) {
                Log.w(AgentService.TAG, "refused peer uid " + uid);
                closeQuietly(peer);
                continue;
            }
            Client client = new Client(peer);
            clients.add(client);
            client.start();
        }
    }

    /** Push one event line to every client. */
    void broadcast(JSONObject event) {
        if (clients.isEmpty()) return;
        String line = event.toString() + "\n";
        for (Client client : clients) client.send(line);
    }

    void close() {
        closed = true;
        if (socket != null) {
            // close() alone does not wake a thread blocked in accept() on an abstract socket.
            try { Os.shutdown(socket.getFileDescriptor(), OsConstants.SHUT_RDWR); } catch (Exception ignored) { }
            try { socket.close(); } catch (IOException ignored) { }
        }
        for (Client client : clients) client.close();
        writer.shutdown();
    }

    private static void closeQuietly(LocalSocket peer) {
        try { peer.close(); } catch (IOException ignored) { }
    }

    private final class Client extends Thread {
        private final LocalSocket peer;
        private OutputStream out;

        Client(LocalSocket peer) {
            super("obsidience-tv-client");
            setDaemon(true);
            this.peer = peer;
        }

        @Override public void run() {
            try {
                out = peer.getOutputStream();
                InputStream in = peer.getInputStream();
                ByteArrayOutputStream line = new ByteArrayOutputStream();
                int b;
                while (!closed && (b = in.read()) != -1) {
                    if (b != '\n') {
                        if (line.size() >= MAX_LINE) break;  // An oversized request ends the connection.
                        line.write(b);
                        continue;
                    }
                    final String text = new String(line.toByteArray(), StandardCharsets.UTF_8);
                    line.reset();
                    if (text.trim().isEmpty()) continue;
                    main.post(() -> {
                        JSONObject response;
                        try {
                            response = handler.handle(new JSONObject(text));
                        } catch (Exception e) {
                            response = AgentService.error(null, "bad request: " + e.getMessage());
                        }
                        send(response.toString() + "\n");
                    });
                }
            } catch (IOException ignored) {
            } finally {
                close();
            }
        }

        void send(String line) {
            try {
                writer.execute(() -> {
                    try {
                        OutputStream stream = out;
                        if (stream == null) return;
                        stream.write(line.getBytes(StandardCharsets.UTF_8));
                        stream.flush();
                    } catch (IOException e) {
                        close();
                    }
                });
            } catch (java.util.concurrent.RejectedExecutionException ignored) { }
        }

        void close() {
            clients.remove(this);
            closeQuietly(peer);
        }
    }
}

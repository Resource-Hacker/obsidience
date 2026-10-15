pragma Singleton
pragma ComponentBehavior: Bound

import QtQml
import Quickshell

// The Harness's local HTTP and WebSocket API as the Shell consumes it: one
// origin, one request() and one reading of its error replies.
Singleton {
    id: root

    readonly property string origin: "http://127.0.0.1:8765"
    readonly property string socketOrigin: "ws://127.0.0.1:8765"

    // Sends body (when not null) as JSON and calls callback once the request is
    // done or aborted, with {ok, status, text}; ok means a 2xx status. Returns
    // the XMLHttpRequest so its owner can abort it.
    function request(method, path, body, callback, headers) {
        const xhr = new XMLHttpRequest()
        xhr.open(method, origin + path)
        if (body !== null && body !== undefined) {
            xhr.setRequestHeader("Content-Type", "application/json")
        }
        for (const name of Object.keys(headers || {})) {
            xhr.setRequestHeader(name, headers[name])
        }
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return
            }
            const status = xhr.status
            callback({"ok": status >= 200 && status < 300, "status": status,
                "text": xhr.responseText || ""})
        }
        xhr.send(body === null || body === undefined ? null : JSON.stringify(body))
        return xhr
    }

    // Harness errors carry {"detail": "..."}; any other body is already
    // readable text.
    function errorText(reply, fallback) {
        const text = reply.text.trim()
        try {
            const parsed = JSON.parse(text)
            if (parsed && typeof parsed.detail === "string" && parsed.detail) {
                return parsed.detail
            }
        } catch (error) {
            // Plain-text failures are already useful.
        }
        return text || fallback + " (" + reply.status + ")"
    }
}

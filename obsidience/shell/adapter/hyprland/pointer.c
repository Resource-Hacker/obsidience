/*
 * Private, one-shot Shell pointer transport. Target authority stays in the
 * existing Shell Scene adapter; a sync receipt is not application acceptance.
 *
 * Pointer button/frame and callback pattern adapted from wlrctl pointer.c,
 * commit c6bc60820bb8786c7509e651bcae9393a738f180.
 * MIT License -- Copyright (c) 2020 Ronan Pigott
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <linux/input-event-codes.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include "wlr-virtual-pointer-unstable-v1-client-protocol.h"

#define MAX_OUTPUTS 32
#define MAX_EXTENT 65536

struct state;
struct output {
    struct state *owner;
    struct wl_output *proxy;
    uint32_t global;
    char name[256];
    int32_t transform;
    bool geometry, done;
};
struct state {
    struct wl_display *display;
    struct wl_registry *registry;
    struct zwlr_virtual_pointer_manager_v1 *manager;
    struct zwlr_virtual_pointer_v1 *pointer;
    struct output outputs[MAX_OUTPUTS], *selected;
    size_t count;
    uint32_t manager_global;
    bool invalid, sealed;
    int64_t deadline;
};

static int64_t now_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0) _exit(1);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void deadline_signal(int signal_number) {
    (void)signal_number;
    _exit(124); /* Final backstop, including connect and blocked stdout. */
}

static void output_changed(struct output *output) {
    if (output->owner->sealed && output == output->owner->selected)
        output->owner->invalid = true;
}
static void output_geometry(void *data, struct wl_output *proxy, int32_t x,
        int32_t y, int32_t pw, int32_t ph, int32_t subpixel, const char *make,
        const char *model, int32_t transform) {
    (void)proxy; (void)x; (void)y; (void)pw; (void)ph;
    (void)subpixel; (void)make; (void)model;
    struct output *output = data;
    output_changed(output);
    output->transform = transform;
    output->geometry = true;
}
static void output_mode(void *data, struct wl_output *proxy, uint32_t flags,
        int32_t width, int32_t height, int32_t refresh) {
    (void)proxy; (void)flags; (void)width; (void)height; (void)refresh;
    output_changed(data);
}
static void output_done(void *data, struct wl_output *proxy) {
    (void)proxy;
    ((struct output *)data)->done = true;
}
static void output_scale(void *data, struct wl_output *proxy, int32_t scale) {
    (void)proxy; (void)scale;
    output_changed(data);
}
static void output_name(void *data, struct wl_output *proxy, const char *name) {
    (void)proxy;
    struct output *output = data;
    output_changed(output);
    if (strlen(name) >= sizeof(output->name)) output->owner->invalid = true;
    else strcpy(output->name, name);
}
static void output_description(void *data, struct wl_output *proxy, const char *description) {
    (void)data; (void)proxy; (void)description;
}
static const struct wl_output_listener output_listener = {
    .geometry = output_geometry, .mode = output_mode, .done = output_done,
    .scale = output_scale, .name = output_name, .description = output_description,
};

static void registry_global(void *data, struct wl_registry *registry,
        uint32_t name, const char *interface, uint32_t version) {
    struct state *state = data;
    if (!strcmp(interface, wl_output_interface.name)) {
        if (state->sealed || state->count == MAX_OUTPUTS) {
            state->invalid = true;
            return;
        }
        if (version < 4) return; /* Exact output names require wl_output v4. */
        struct output *output = &state->outputs[state->count++];
        output->owner = state;
        output->global = name;
        output->proxy = wl_registry_bind(registry, name, &wl_output_interface, 4);
        wl_output_add_listener(output->proxy, &output_listener, output);
    } else if (!strcmp(interface, zwlr_virtual_pointer_manager_v1_interface.name)) {
        if (state->manager || version < 2) {
            state->invalid = true;
            return;
        }
        state->manager_global = name;
        state->manager = wl_registry_bind(registry, name,
            &zwlr_virtual_pointer_manager_v1_interface, 2);
    }
}
static void registry_remove(void *data, struct wl_registry *registry, uint32_t name) {
    (void)registry;
    struct state *state = data;
    if (name == state->manager_global) state->invalid = true;
    for (size_t i = 0; i < state->count; ++i) {
        if (state->outputs[i].global == name) state->invalid = true;
    }
}
static const struct wl_registry_listener registry_listener = {
    .global = registry_global, .global_remove = registry_remove,
};

/* One libwayland owner: prepare/read/cancel remains paired on every exit.
 * Poll also services compositor removal/error events while awaiting commit. */
static int pump(struct state *state, int64_t deadline, bool watch_stdin) {
    if (wl_display_dispatch_pending(state->display) < 0 || state->invalid) return -1;
    while (wl_display_prepare_read(state->display) < 0) {
        if (wl_display_dispatch_pending(state->display) < 0 || state->invalid) return -1;
    }
    int flushed = wl_display_flush(state->display);
    if (flushed < 0 && errno != EAGAIN) {
        wl_display_cancel_read(state->display);
        return -1;
    }
    struct pollfd fds[2] = {
        {wl_display_get_fd(state->display), POLLIN | (flushed < 0 ? POLLOUT : 0), 0},
        {watch_stdin ? STDIN_FILENO : -1, POLLIN, 0},
    };
    int64_t remaining = deadline - now_ms();
    int ready = remaining > 0 ? poll(fds, 2, (int)remaining) : 0;
    if (ready <= 0) {
        wl_display_cancel_read(state->display);
        return ready < 0 && errno == EINTR ? 0 : -1;
    }
    if (fds[0].revents & POLLIN) {
        if (wl_display_read_events(state->display) < 0) return -1;
    } else wl_display_cancel_read(state->display);
    if ((fds[0].revents & (POLLERR | POLLHUP | POLLNVAL)) ||
            wl_display_dispatch_pending(state->display) < 0 || state->invalid) return -1;
    return fds[1].revents & (POLLIN | POLLHUP | POLLERR | POLLNVAL) ? 1 : 0;
}
static void sync_done(void *data, struct wl_callback *callback, uint32_t serial) {
    (void)callback; (void)serial;
    *(bool *)data = true;
}
static const struct wl_callback_listener sync_listener = {.done = sync_done};
static bool roundtrip(struct state *state) {
    bool done = false;
    struct wl_callback *callback = wl_display_sync(state->display);
    if (!callback) return false;
    wl_callback_add_listener(callback, &sync_listener, &done);
    while (!done && !state->invalid) {
        if (pump(state, state->deadline, false) < 0) break;
    }
    wl_callback_destroy(callback);
    return done && !state->invalid && !wl_display_get_error(state->display);
}
static bool await_commit(struct state *state) {
    int64_t deadline = now_ms() + 2000;
    if (deadline > state->deadline) deadline = state->deadline;
    char command[8];
    size_t used = 0;
    for (;;) {
        int ready = pump(state, deadline, true);
        if (ready < 0) return false;
        if (!ready) continue;
        ssize_t received = read(STDIN_FILENO, command + used, sizeof(command) - used);
        if (received <= 0) return false;
        used += (size_t)received;
        if (memchr(command, '\n', used))
            return used == 7 && !memcmp(command, "commit\n", 7);
        if (used == sizeof(command)) return false;
    }
}
static bool number(const char *text, uint32_t *value) {
    if (!*text || strspn(text, "0123456789") != strlen(text)) return false;
    errno = 0;
    char *end;
    unsigned long parsed = strtoul(text, &end, 10);
    if (errno || *end || parsed > MAX_EXTENT) return false;
    *value = (uint32_t)parsed;
    return true;
}
static bool receipt(const char *status) {
    return printf("{\"status\":\"%s\"}\n", status) > 0 && fflush(stdout) == 0;
}
int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    signal(SIGALRM, deadline_signal);
    alarm(5);
    struct state state = {.deadline = now_ms() + 5000};
    uint32_t x, y, width, height;
    if (argc != 6 || !argv[1][0] || strlen(argv[1]) > 255 ||
            !number(argv[2], &x) || !number(argv[3], &y) ||
            !number(argv[4], &width) || !number(argv[5], &height) ||
            !width || !height || x >= width || y >= height) {
        fputs("invalid output or output-local logical coordinates\n", stderr);
        return 2;
    }
    int result = 1;
    state.display = wl_display_connect(NULL);
    if (!state.display) goto finished;
    state.registry = wl_display_get_registry(state.display);
    wl_registry_add_listener(state.registry, &registry_listener, &state);
    if (!roundtrip(&state) || !roundtrip(&state) || !state.manager) goto finished;
    for (size_t i = 0; i < state.count; ++i) {
        struct output *output = &state.outputs[i];
        if (strcmp(output->name, argv[1])) continue;
        if (state.selected || !output->done || !output->geometry ||
                output->transform != WL_OUTPUT_TRANSFORM_NORMAL) goto finished;
        state.selected = output;
    }
    if (!state.selected) goto finished;
    state.sealed = true;
    state.pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer_with_output(
        state.manager, NULL, state.selected->proxy);
    if (!state.pointer) goto finished;
    zwlr_virtual_pointer_v1_motion_absolute(state.pointer, (uint32_t)now_ms(), x, y, width, height);
    zwlr_virtual_pointer_v1_frame(state.pointer);
    if (!roundtrip(&state) || !receipt("positioned") || !await_commit(&state)) goto finished;
    /* One commit, one down/up pair, both complete frames on the same device.
     * Never retry after entering this block, including a missing callback. */
    zwlr_virtual_pointer_v1_button(state.pointer, (uint32_t)now_ms(), BTN_LEFT, WL_POINTER_BUTTON_STATE_PRESSED);
    zwlr_virtual_pointer_v1_frame(state.pointer);
    zwlr_virtual_pointer_v1_button(state.pointer, (uint32_t)now_ms(), BTN_LEFT, WL_POINTER_BUTTON_STATE_RELEASED);
    zwlr_virtual_pointer_v1_frame(state.pointer);
    if (roundtrip(&state) && receipt("acknowledged")) result = 0;
finished:
    if (state.pointer) zwlr_virtual_pointer_v1_destroy(state.pointer);
    if (state.manager) zwlr_virtual_pointer_manager_v1_destroy(state.manager);
    for (size_t i = 0; i < state.count; ++i) wl_output_destroy(state.outputs[i].proxy);
    if (state.registry) wl_registry_destroy(state.registry);
    if (state.display) {
        wl_display_flush(state.display);
        wl_display_disconnect(state.display);
    }
    if (result) fputs("pointer transaction aborted; never replay an uncertain commit\n", stderr);
    return result;
}

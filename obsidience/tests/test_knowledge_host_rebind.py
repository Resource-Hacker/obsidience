"""A physical monitor return must preserve the logical Surface's resident page."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


HOST = Path(__file__).parents[1] / "shell/surfaces/knowledge/host.py"


class Signals:
    def __init__(self):
        self.signals = {}

    def connect(self, name, callback):
        self.signals[name] = callback


class Monitor(Signals):
    def __init__(self, width, height):
        super().__init__()
        self.geometry = SimpleNamespace(width=width, height=height)

    def get_geometry(self):
        return self.geometry


class Window(Signals):
    def __init__(self, **_kwargs):
        super().__init__()
        self.visible = False
        self.hide_count = 0
        self.child = None

    def set_title(self, value):
        self.title = value

    def set_decorated(self, value):
        self.decorated = value

    def set_accept_focus(self, value):
        self.accept_focus = value

    def add(self, child):
        assert self.child is None, "A resident WebView must not be replaced"
        self.child = child

    def hide(self):
        self.visible = False
        self.hide_count += 1

    def show_all(self):
        self.visible = True


class View(Signals):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.network_available = True
        self.page_state = {"resident": object()}

    def get_settings(self):
        return SimpleNamespace(
            set_enable_webgl=lambda _value: None,
            set_hardware_acceleration_policy=lambda _value: None,
        )

    def set_background_color(self, _value):
        pass

    def load_request(self, request):
        assert self.network_available, "Unexpected navigation while Harness is offline"
        self.requests.append(request)


class Request:
    def __init__(self, uri):
        self.uri = uri
        self.headers = {}

    def get_http_headers(self):
        return SimpleNamespace(replace=self.headers.__setitem__)


@pytest.fixture
def host_fixture(tmp_path):
    # Compile the real class without importing GI, setting process environment,
    # opening a display, starting a file watcher, or sending an HTTP request.
    tree = ast.parse(HOST.read_text())
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "KnowledgeDesktop")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, definition], type_ignores=[]))
    display = Signals()
    display.monitors = [Monitor(1920, 1200), Monitor(1920, 550)]
    display.get_n_monitors = lambda: len(display.monitors)
    display.get_monitor = lambda index: display.monitors[index]
    layout = tmp_path / "surface-layout.json"
    layout.write_text(json.dumps({"graph_surface_id": "usb-c"}))
    queued, bindings = [], []
    layer = SimpleNamespace(
        init_for_window=lambda _window: None,
        set_namespace=lambda *_args: None,
        set_monitor=lambda window, monitor: bindings.append((window, monitor)),
        set_layer=lambda *_args: None,
        set_exclusive_zone=lambda *_args: None,
        set_keyboard_mode=lambda window, mode: setattr(window, "keyboard_mode", mode),
        set_anchor=lambda *_args: None,
        Layer=SimpleNamespace(BACKGROUND=0),
        KeyboardMode=SimpleNamespace(ON_DEMAND=2),
        Edge=SimpleNamespace(TOP=0, RIGHT=1, BOTTOM=2, LEFT=3),
    )
    namespace = {
        "json": json, "LAYOUT_PATH": layout,
        "SURFACE_SIZES": {"samsung": (5120, 1440), "usb-c": (1920, 1200), "dp-4": (1920, 550)},
        "KNOWLEDGE_ORIGIN": "http://127.0.0.1:8765/shell/knowledge/",
        "Gio": SimpleNamespace(
            File=SimpleNamespace(new_for_path=lambda _path: SimpleNamespace(
                monitor_directory=lambda *_args: Signals())),
            FileMonitorFlags=SimpleNamespace(NONE=0),
        ),
        "GLib": SimpleNamespace(idle_add=lambda callback: queued.append(callback)),
        "Gdk": SimpleNamespace(RGBA=lambda *values: values),
        "Gtk": SimpleNamespace(Window=Window, WindowType=SimpleNamespace(TOPLEVEL=0)),
        "GtkLayerShell": layer,
        "WebKit2": SimpleNamespace(WebView=View, URIRequest=SimpleNamespace(new=Request),
            HardwareAccelerationPolicy=SimpleNamespace(ALWAYS=0), LoadEvent=SimpleNamespace(FINISHED=0)),
    }
    exec(compile(module, str(HOST), "exec"), namespace)

    def flush():
        while queued:
            assert queued.pop(0)() is False

    return SimpleNamespace(cls=namespace["KnowledgeDesktop"], display=display,
                           layout=layout, bindings=bindings, flush=flush)


@pytest.mark.parametrize("replace_monitor", [False, True], ids=["geometry-return", "new-monitor-object"])
def test_same_surface_return_keeps_page_when_harness_is_offline(host_fixture, replace_monitor):
    f = host_fixture
    host = f.cls(f.display)
    window, view = host.window, host.webview
    resident = view.page_state
    original = host.monitor
    assert len(view.requests) == 1 and window.visible
    view.network_available = False
    if replace_monitor:
        f.display.monitors.remove(original)
        f.display.signals["monitor-removed"](original)
    else:
        original.geometry.width = 720
        original.signals["notify::geometry"](original)
    f.flush()
    assert host.monitor is None and not window.visible
    assert host.surface_id == "usb-c" and window.hide_count == 1
    assert host.window is window and host.webview is view
    if replace_monitor:
        returned = Monitor(1920, 1200)
        f.display.monitors.append(returned)
        f.display.signals["monitor-added"](returned)
    else:
        returned = original
        original.geometry.width = 1920
        original.signals["notify::geometry"](original)
    # Multiple queued display notifications must settle to the same binding.
    host._monitor_changed()
    f.flush()
    assert host.monitor is returned and host.surface_id == "usb-c"
    assert host.window is window and window.child is view and host.webview is view
    assert view.page_state is resident and len(view.requests) == 1
    assert f.bindings[-1] == (window, returned) and window.visible


@pytest.mark.parametrize("temporarily_absent", [False, True], ids=["available-target", "target-arrives-later"])
def test_actual_surface_change_navigates_once_on_the_resident_view(host_fixture, temporarily_absent):
    f = host_fixture
    host = f.cls(f.display)
    window, view = host.window, host.webview
    target = f.display.monitors[1]
    if temporarily_absent:
        f.display.monitors.remove(target)
    f.layout.write_text(json.dumps({"graph_surface_id": "dp-4"}))
    host.layout_monitor.signals["changed"]()
    f.flush()
    if temporarily_absent:
        assert host.monitor is None and len(view.requests) == 1 and not window.visible
        assert host.surface_id == "usb-c"  # Page identity is retained until actual retarget.
        f.display.monitors.append(target)
        f.display.signals["monitor-added"](target)
        f.flush()
    host.refresh()
    assert host.window is window and host.webview is view and window.child is view
    assert host.monitor is target and host.surface_id == "dp-4" and window.visible
    assert [request.uri for request in view.requests] == [
        host._knowledge_url("usb-c"), host._knowledge_url("dp-4"),
    ]
    assert all(request.headers == {"Cache-Control": "no-cache"} for request in view.requests)


def test_initially_absent_surface_creates_one_view_when_monitor_arrives(host_fixture):
    f = host_fixture
    monitor = f.display.monitors.pop(0)
    host = f.cls(f.display)
    assert host.window is None and host.webview is None and host.monitor is None
    f.display.monitors.append(monitor)
    f.display.signals["monitor-added"](monitor)
    f.flush()
    assert host.window.visible and host.window.child is host.webview
    assert host.window.accept_focus is True and host.window.decorated is False
    assert host.window.keyboard_mode == 2  # Native on-demand focus, never exclusive.
    assert host.webview.requests[0].uri == host._knowledge_url("usb-c")
    assert host.webview.requests[0].headers == {"Cache-Control": "no-cache"}
    host.refresh()
    assert len(host.webview.requests) == 1

from pathlib import Path
import site
import sys


system_site = (
    Path(sys.base_prefix)
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
if system_site.is_dir():
    site.addsitedir(str(system_site))

from obsidience.shell.surfaces.lock.host import (
    KNOWLEDGE_URL,
    SideGraphPresenter,
    lock_active,
    selected_graph_surface,
)


ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "obsidience" / "shell"


def test_lock_state_is_exact_and_fails_closed(tmp_path: Path) -> None:
    state = tmp_path / "lock-state"

    assert lock_active(state) is True
    state.write_bytes(b"1\n")
    assert lock_active(state) is True
    state.write_bytes(b"0\n")
    assert lock_active(state) is False
    state.write_bytes(b" 0\n")
    assert lock_active(state) is True
    state.write_bytes(b"invalid")
    assert lock_active(state) is True


def test_graph_surface_selection_is_exact_and_defaults_to_samsung(
    tmp_path: Path,
) -> None:
    layout = tmp_path / "surface-layout.json"

    assert selected_graph_surface(layout) == "samsung"
    layout.write_text('{"graph_surface_id":"usb-c"}\n')
    assert selected_graph_surface(layout) == "usb-c"
    layout.write_text('{"graph_surface_id":"dp-4"}\n')
    assert selected_graph_surface(layout) == "dp-4"
    layout.write_text('{"graph_surface_id":"unknown"}\n')
    assert selected_graph_surface(layout) == "samsung"
    layout.write_text("invalid")
    assert selected_graph_surface(layout) == "samsung"


def test_side_graph_presenter_has_one_four_mode_state_machine(tmp_path: Path) -> None:
    lock_state = tmp_path / "lock-state"
    layout = tmp_path / "surface-layout.json"
    presenter = SideGraphPresenter.__new__(SideGraphPresenter)
    presenter.surface_id = "usb-c"
    presenter.lock_path = lock_state
    presenter.layout_path = layout

    lock_state.write_text("0\n")
    layout.write_text('{"graph_surface_id":"samsung"}\n')
    assert presenter.desired_mode() == "hidden"
    layout.write_text('{"graph_surface_id":"usb-c"}\n')
    assert presenter.desired_mode() == "desktop-graph"
    lock_state.write_text("1\n")
    assert presenter.desired_mode() == "lock-graph"
    layout.write_text('{"graph_surface_id":"dp-4"}\n')
    assert presenter.desired_mode() == "lock-solid"


def test_side_graph_host_reuses_canonical_graph_and_lock_is_input_empty() -> None:
    host = (SHELL / "surfaces" / "lock" / "host.py").read_text()

    assert KNOWLEDGE_URL.endswith("/shell/knowledge/?surface=knowledge")
    assert 'os.environ.setdefault("GDK_BACKEND", "x11")' in host
    assert "Gio.FileMonitorFlags.NONE" in host
    assert "monitor_directory" in host
    assert "Gtk.WindowType.POPUP" in host
    assert "Gtk.WindowType.TOPLEVEL" in host
    assert "set_keep_above(True)" in host
    assert "set_keep_below(True)" in host
    assert "Gdk.WindowTypeHint.DESKTOP" in host
    assert "input_shape_combine_region(cairo.Region(), 0, 0)" in host
    assert "self.window.destroy()" in host
    assert "GLib.timeout_add_seconds(1, self._retry_load)" in host
    assert 'return "lock-graph" if selected else "lock-solid"' in host
    assert 'return "desktop-graph" if selected else "hidden"' in host
    assert "QtWebEngine" not in host
    assert "password" not in host.lower()
    assert "authenticator" not in host.lower()


def test_each_side_surface_has_one_lock_presenter_unit() -> None:
    units = {
        "usb-c": (
            SHELL / "systemd" / "obsidience-shell-lock-usbc.service",
            ":2.0",
        ),
        "dp-4": (
            SHELL / "systemd" / "obsidience-shell-lock-dp4.service",
            ":2.1",
        ),
    }
    host_path = (
        "/home/wissenschafter/Projects/obsidience/"
        "obsidience/shell/surfaces/lock/host.py"
    )

    for path, display in units.values():
        unit = path.read_text()
        assert f"Environment=DISPLAY={display}" in unit
        assert f"DISPLAY={display} /usr/bin/xdpyinfo" in unit
        assert f"ExecStart=/usr/bin/python3 {host_path}" in unit
        assert "surface=knowledge&surface_id=" in unit
        assert "OBSIDIENCE_SURFACE_LAYOUT=" in unit
        assert "Requires=usb-monitor-xorg.service" in unit
        assert "PartOf=usb-monitor-xorg.service graphical-session.target" in unit
    assert "Environment=OBSIDIENCE_SURFACE_ID=usb-c" in units["usb-c"][0].read_text()
    assert "Environment=OBSIDIENCE_SURFACE_ID=dp-4" in units["dp-4"][0].read_text()

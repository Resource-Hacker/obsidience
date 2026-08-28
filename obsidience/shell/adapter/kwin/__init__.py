"""Bounded KWin observation for the native Obsidience shell."""

from .observer import BUS_NAME, KWinObserver, WindowState, parse_window_list

__all__ = ["BUS_NAME", "KWinObserver", "WindowState", "parse_window_list"]

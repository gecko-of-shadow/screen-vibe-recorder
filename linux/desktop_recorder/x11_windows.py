"""X11 window list for the region selector.

The pure core (window_rect, visible_rects) runs on any OS.
list_windows imports python-xlib inside the function only, so this module imports on Windows too.
All values are physical px (X screen px).
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Rect

__all__ = ["XWin", "SKIP_TYPES", "window_rect", "visible_rects", "list_windows"]


@dataclass
class XWin:
    xid: int
    x: int
    y: int
    w: int
    h: int                                            # client area in root coordinates
    frame_extents: tuple[int, int, int, int] | None   # _NET_FRAME_EXTENTS (l, r, t, b)
    gtk_extents: tuple[int, int, int, int] | None     # _GTK_FRAME_EXTENTS (l, r, t, b)
    types: list[str]                                  # _NET_WM_WINDOW_TYPE atom names
    states: list[str]                                 # _NET_WM_STATE atom names
    viewable: bool
    override_redirect: bool
    pid: int | None                                   # _NET_WM_PID


SKIP_TYPES = {"_NET_WM_WINDOW_TYPE_DOCK", "_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_TOOLBAR",
              "_NET_WM_WINDOW_TYPE_MENU", "_NET_WM_WINDOW_TYPE_UTILITY", "_NET_WM_WINDOW_TYPE_SPLASH",
              "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU", "_NET_WM_WINDOW_TYPE_POPUP_MENU",
              "_NET_WM_WINDOW_TYPE_TOOLTIP", "_NET_WM_WINDOW_TYPE_NOTIFICATION"}

_HIDDEN = "_NET_WM_STATE_HIDDEN"


def window_rect(win: XWin) -> Rect:
    """The visible bounds of a window.

    First grow by _NET_FRAME_EXTENTS (the window manager frame).
    Then shrink by _GTK_FRAME_EXTENTS (the client-side shadow).
    Mutter can set both on one window, so apply both, in this order.
    """
    x, y, w, h = win.x, win.y, win.w, win.h
    if win.frame_extents is not None:
        l, r, t, b = win.frame_extents
        x, y, w, h = x - l, y - t, w + l + r, h + t + b
    if win.gtk_extents is not None:
        l, r, t, b = win.gtk_extents
        x, y, w, h = x + l, y + t, w - l - r, h - t - b
    return Rect(x, y, w, h)


def _skip(win: XWin) -> bool:
    if not win.viewable or win.override_redirect:
        return True
    if _HIDDEN in win.states:
        return True
    return any(t in SKIP_TYPES for t in win.types)


def visible_rects(bottom_to_top: list[XWin], screen: Rect) -> list[Rect]:
    """Rects of the windows that the selector can detect, clipped to the screen, top window first.

    No window is skipped by pid (D25): the Settings dialog of this app can be selected.
    """
    result: list[Rect] = []
    for win in reversed(bottom_to_top):
        if _skip(win):
            continue
        r = window_rect(win).intersect(screen)
        if r.w < 2 or r.h < 2:
            continue
        result.append(r)
    return result


# ---------------------------------------------------------------- python-xlib reader


def _cardinals4(win, atom) -> tuple[int, int, int, int] | None:
    from Xlib import X

    prop = win.get_full_property(atom, X.AnyPropertyType)
    if prop is None or prop.value is None or len(prop.value) < 4:
        return None
    v = prop.value
    return (int(v[0]), int(v[1]), int(v[2]), int(v[3]))


def _atom_names(display, win, atom, cache: dict[int, str]) -> list[str]:
    from Xlib import X

    prop = win.get_full_property(atom, X.AnyPropertyType)
    if prop is None or prop.value is None:
        return []
    names: list[str] = []
    for a in prop.value:
        a = int(a)
        if a not in cache:
            try:
                cache[a] = display.get_atom_name(a)
            except Exception:
                cache[a] = ""
        names.append(cache[a])
    return names


def _pid(win, atom) -> int | None:
    from Xlib import X

    prop = win.get_full_property(atom, X.AnyPropertyType)
    if prop is None or prop.value is None or len(prop.value) < 1:
        return None
    return int(prop.value[0])


def list_windows(display_name: str | None) -> list[Rect]:
    """Window rects in physical px, top window first.

    Uses _NET_CLIENT_LIST_STACKING when a window manager sets it.
    Else uses XQueryTree (no window manager, for example Xvfb).
    A window that gives an X error is skipped.
    """
    from Xlib import X, display as xdisplay, error as xerror

    disp = xdisplay.Display(display_name) if display_name else xdisplay.Display()
    try:
        root = disp.screen().root
        screen = Rect(0, 0, int(disp.screen().width_in_pixels), int(disp.screen().height_in_pixels))

        a_stacking = disp.intern_atom("_NET_CLIENT_LIST_STACKING")
        a_frame = disp.intern_atom("_NET_FRAME_EXTENTS")
        a_gtk = disp.intern_atom("_GTK_FRAME_EXTENTS")
        a_type = disp.intern_atom("_NET_WM_WINDOW_TYPE")
        a_state = disp.intern_atom("_NET_WM_STATE")
        a_pid = disp.intern_atom("_NET_WM_PID")

        windows = []
        try:
            prop = root.get_full_property(a_stacking, X.AnyPropertyType)
        except xerror.XError:
            prop = None
        if prop is not None and prop.value is not None and len(prop.value) > 0:
            windows = [disp.create_resource_object("window", int(xid)) for xid in prop.value]
        else:
            windows = list(root.query_tree().children)  # bottom-to-top order

        cache: dict[int, str] = {}
        wins: list[XWin] = []
        for win in windows:
            try:
                attrs = win.get_attributes()
                geom = win.get_geometry()
                # a.translate_coords(src, x, y) converts from src to a.
                t = root.translate_coords(win, 0, 0)
                wins.append(XWin(
                    xid=int(win.id),
                    x=int(t.x),
                    y=int(t.y),
                    w=int(geom.width),
                    h=int(geom.height),
                    frame_extents=_cardinals4(win, a_frame),
                    gtk_extents=_cardinals4(win, a_gtk),
                    types=_atom_names(disp, win, a_type, cache),
                    states=_atom_names(disp, win, a_state, cache),
                    viewable=int(attrs.map_state) == X.IsViewable,
                    override_redirect=bool(attrs.override_redirect),
                    pid=_pid(win, a_pid),
                ))
            except xerror.XError:
                continue
        return visible_rects(wins, screen)
    finally:
        try:
            disp.close()
        except Exception:
            pass

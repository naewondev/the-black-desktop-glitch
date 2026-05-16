"""
Black Desktop Glitch Simulator
--------------------------------
Replicates the classic Windows black desktop rendering glitch.
- Covers only the primary monitor work area (excludes taskbar)
- Click and drag to reveal the desktop underneath
- Auto-closes when the entire covered area has been revealed
- Press ESC to exit at any time
"""

import pygame
import sys
import ctypes
import ctypes.wintypes

# ── Windows API ────────────────────────────────────────────────────────────
user32 = ctypes.windll.user32
gdi32  = ctypes.windll.gdi32

GWL_EXSTYLE      = -20
GWL_STYLE        = -16
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP         = 0x80000000
HWND_BOTTOM      = 1
SWP_NOMOVE       = 0x0002
SWP_NOSIZE       = 0x0001
SWP_NOACTIVATE   = 0x0010
SWP_SHOWWINDOW   = 0x0040
SM_CXSCREEN      = 0
SM_CYSCREEN      = 1
RGN_DIFF         = 4

# SystemParametersInfo
SPI_GETWORKAREA  = 0x0030


def get_screen_size():
    return user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)


def get_work_area():
    """
    Returns the usable desktop RECT — full screen minus the taskbar.
    This is the area our window actually covers.
    """
    rc = ctypes.wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rc), 0)
    return rc.left, rc.top, rc.right, rc.bottom


def get_hwnd():
    return pygame.display.get_wm_info().get("window")


def setup_window(hwnd, wx, wy, ww, wh):
    """Position window to cover exactly the work area."""
    user32.SetWindowLongW(hwnd, GWL_STYLE, WS_POPUP)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    user32.SetWindowPos(hwnd, HWND_BOTTOM, wx, wy, ww, wh,
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)


def push_to_bottom(hwnd):
    user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def is_lmb_down():
    return (user32.GetAsyncKeyState(0x01) & 0x8000) != 0


def is_esc_down():
    return (user32.GetAsyncKeyState(0x1B) & 0x8000) != 0


def get_cursor_pos():
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def build_region(ww, wh, holes):
    """Work-area-sized region minus all revealed holes."""
    full = gdi32.CreateRectRgn(0, 0, ww, wh)
    for (l, t, r, b) in holes:
        if r > l and b > t:
            hole_rgn = gdi32.CreateRectRgn(l, t, r, b)
            gdi32.CombineRgn(full, full, hole_rgn, RGN_DIFF)
            gdi32.DeleteObject(hole_rgn)
    return full


def apply_region(hwnd, ww, wh, holes):
    rgn = build_region(ww, wh, holes)
    user32.SetWindowRgn(hwnd, rgn, True)


def quit_clean(hwnd):
    user32.SetWindowRgn(hwnd, None, True)
    pygame.quit()
    sys.exit(0)


def union_area(rects):
    """
    Total area covered by a list of (l, t, r, b) rects — overlap-proof.
    Uses coordinate-compression sweep line.
    """
    if not rects:
        return 0

    xs = sorted(set(x for r in rects for x in (r[0], r[2])))
    total = 0

    for i in range(len(xs) - 1):
        x1, x2  = xs[i], xs[i + 1]
        band_w  = x2 - x1

        intervals = [(t, b) for (l, t, r, b) in rects if l <= x1 and x2 <= r]
        if not intervals:
            continue

        intervals.sort()
        merged_h = 0
        ct, cb   = intervals[0]
        for (t, b) in intervals[1:]:
            if t <= cb:
                cb = max(cb, b)
            else:
                merged_h += cb - ct
                ct, cb    = t, b
        merged_h += cb - ct
        total    += band_w * merged_h

    return total


def main():
    pygame.init()

    # Full screen size (for pygame surface)
    sw, sh = get_screen_size()

    # Work area: desktop minus taskbar
    wa_left, wa_top, wa_right, wa_bottom = get_work_area()
    ww = wa_right  - wa_left   # work area width
    wh = wa_bottom - wa_top    # work area height
    total_pixels = ww * wh

    # Threshold: 99% coverage triggers auto-close
    # Handles users who can't quite reach the very edges
    THRESHOLD = 0.99

    # pygame window sized to work area only
    screen = pygame.display.set_mode((ww, wh), pygame.NOFRAME)
    pygame.display.set_caption("Black Desktop Glitch")

    hwnd = get_hwnd()
    if hwnd:
        setup_window(hwnd, wa_left, wa_top, ww, wh)

    holes = []
    apply_region(hwnd, ww, wh, holes)

    clock        = pygame.time.Clock()
    dragging     = False
    drag_start   = (0, 0)
    was_pressed  = False
    region_dirty = False
    check_area   = False

    while True:

        if is_esc_down():
            quit_clean(hwnd)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                quit_clean(hwnd)

        # ── Mouse input ──────────────────────────────────────────────────────
        lmb        = is_lmb_down()
        gx, gy     = get_cursor_pos()           # global screen coords

        # Convert global coords to window-local coords
        lx = gx - wa_left
        ly = gy - wa_top

        if lmb and not was_pressed:
            dragging   = True
            drag_start = (lx, ly)

        if not lmb and was_pressed and dragging:
            x1, y1 = drag_start
            x2, y2 = lx, ly
            l, r   = min(x1, x2), max(x1, x2)
            t, b   = min(y1, y2), max(y1, y2)

            # Clamp strictly to window bounds
            l = max(0, l)
            t = max(0, t)
            r = min(ww, r)
            b = min(wh, b)

            if r - l > 2 and b - t > 2:
                holes.append((l, t, r, b))
                region_dirty = True
                check_area   = True
            dragging = False

        if not lmb:
            dragging = False

        was_pressed = lmb

        # ── Rebuild window region ────────────────────────────────────────────
        if region_dirty:
            apply_region(hwnd, ww, wh, holes)
            region_dirty = False

        # ── Check if fully revealed ──────────────────────────────────────────
        if check_area:
            revealed = union_area(holes)
            if revealed >= total_pixels * THRESHOLD:
                quit_clean(hwnd)
            check_area = False

        # ── Render ───────────────────────────────────────────────────────────
        screen.fill((0, 0, 0))

        for (l, t, r, b) in holes:
            pygame.draw.rect(screen, (30, 30, 30), (l, t, r - l, b - t), 1)

        if dragging:
            x1, y1 = drag_start
            l = min(x1, lx)
            t = min(y1, ly)
            w = abs(lx - x1)
            h = abs(ly - y1)
            if w > 2 and h > 2:
                pygame.draw.rect(screen, (80, 80, 80), (l, t, w, h), 1)
                drag_surf = pygame.Surface((w, h), pygame.SRCALPHA)
                drag_surf.fill((255, 255, 255, 30))
                screen.blit(drag_surf, (l, t))

        pygame.display.flip()

        push_to_bottom(hwnd)
        clock.tick(60)


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    main()

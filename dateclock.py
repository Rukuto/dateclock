"""
DateClock — large customizable digital clock for Windows with calendar popup.

Rendering: time is drawn with Pillow (antialiased) and shown on a Tk Canvas
so there's no pixelation at large font sizes. Everything below is built on
top of that pipeline.

New in v2:
- Antialiased text (no jagged edges at large sizes)
- Per-digit / per-separator spacing
- Separator as colon, dots (perfect circles), or dashes
- Separator vertical position and radius
- Text outline (stroke) and outline thickness
- Text shadow with blur, offset and color
- Box (background panel) with corner radius, padding (inside), outer margin,
  outline color/thickness, and drop shadow
- Character vertical stretch (height multiplier without changing font)
- Smooth color animation between "on" and "off" blink colors with
  configurable animation duration AND interval (so blink interval and
  transition smoothness are independent)
- All v1 features retained
"""

import sys
import os
import json
import math
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import font as tkfont
from tkinter import colorchooser, messagebox, ttk
import threading
import time
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageGrab, ImageTk

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
APP_NAME = "DateClock"
APPDATA_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = APPDATA_DIR / "config.json"

# One-time migration: if a user upgrades from the older name ("BigClock"),
# copy their existing config into the new DateClock folder so they don't
# lose settings. We only do this on first run when the new location is empty.
_LEGACY_CONFIG = (Path(os.getenv("APPDATA", str(Path.home())))
                  / "BigClock" / "config.json")
if not CONFIG_PATH.exists() and _LEGACY_CONFIG.exists():
    try:
        CONFIG_PATH.write_bytes(_LEGACY_CONFIG.read_bytes())
    except Exception:
        pass

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

# UpdateLayeredWindow flags
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

# SetWindowPos constants (used to re-assert topmost periodically; Tk's own
# -topmost attribute can get knocked off by other apps and never restored)
HWND_TOPMOST    = -1
HWND_NOTOPMOST  = -2
SWP_NOSIZE      = 0x0001
SWP_NOMOVE      = 0x0002
SWP_NOACTIVATE  = 0x0010
SWP_TOPMOST_REASSERT = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE

ANCHORS = [
    "top-left", "top-center", "top-right",
    "middle-left", "middle-center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
]

SEPARATOR_STYLES = ["colon", "dots", "dash", "none"]


# ctypes types for Win32 monitor enumeration
class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


wintypes_HMONITOR = ctypes.c_void_p


# Configure ctypes signatures for the Win32 functions we use. Without this,
# ctypes assumes int args, which truncates pointers on 64-bit Windows and
# crashes with confusing access violations.
def _setup_win32_signatures():
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int

        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL

        gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC, ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, ctypes.c_uint,
        ]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP

        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL

        user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND, wintypes.HDC,
            ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
            wintypes.HDC, ctypes.POINTER(_POINT),
            ctypes.c_uint, ctypes.POINTER(_BLENDFUNCTION), ctypes.c_uint,
        ]
        user32.UpdateLayeredWindow.restype = wintypes.BOOL

        user32.SetWindowPos.argtypes = [
            wintypes.HWND, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
    except Exception:
        pass


try:
    _setup_win32_signatures()
except Exception:
    pass


def paint_layered_window(hwnd, image, x, y):
    """
    Paint a Pillow RGBA image into a layered Win32 window using
    UpdateLayeredWindow. The OS will composite the per-pixel alpha against
    whatever is behind the window — no chroma key, no fringe.

    `image` must be a PIL.Image in RGBA mode. `x, y` are screen coordinates
    of the top-left of the window after the call.
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    width, height = image.size

    # Win32 expects BGRA premultiplied alpha
    # 1) split, premultiply colour by alpha
    r, g, b, a = image.split()
    pr = Image.eval(r, lambda v: v)  # placeholder; we'll build the buffer below

    # Build a BGRA premultiplied byte buffer directly from Pillow
    # (faster than going through Image.eval)
    src = image.tobytes("raw", "RGBA")
    # Premultiply each pixel: (r*a/255, g*a/255, b*a/255, a) then swap to BGRA
    import array
    arr = array.array("B", src)
    for i in range(0, len(arr), 4):
        ai = arr[i + 3]
        if ai == 255:
            ri, gi, bi = arr[i], arr[i + 1], arr[i + 2]
        elif ai == 0:
            ri = gi = bi = 0
        else:
            ri = (arr[i] * ai) // 255
            gi = (arr[i + 1] * ai) // 255
            bi = (arr[i + 2] * ai) // 255
        # BGRA order
        arr[i] = bi
        arr[i + 1] = gi
        arr[i + 2] = ri
        # arr[i+3] stays the alpha
    bgra = bytes(arr)

    # Create a top-down 32-bit DIB section
    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height          # negative => top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0           # BI_RGB
    bmi.bmiHeader.biSizeImage = width * height * 4

    pbits = ctypes.c_void_p()
    screen_dc = user32.GetDC(0)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    hbitmap = gdi32.CreateDIBSection(
        mem_dc, ctypes.byref(bmi), 0,            # DIB_RGB_COLORS
        ctypes.byref(pbits), None, 0,
    )
    old_obj = gdi32.SelectObject(mem_dc, hbitmap)

    # Copy our pixel buffer into the DIB
    ctypes.memmove(pbits, bgra, len(bgra))

    pt_dest = _POINT(x, y)
    sz = _SIZE(width, height)
    pt_src = _POINT(0, 0)
    blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

    user32.UpdateLayeredWindow(
        hwnd,
        screen_dc,
        ctypes.byref(pt_dest),
        ctypes.byref(sz),
        mem_dc,
        ctypes.byref(pt_src),
        0,
        ctypes.byref(blend),
        ULW_ALPHA,
    )

    # Cleanup
    gdi32.SelectObject(mem_dc, old_obj)
    gdi32.DeleteObject(hbitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(0, screen_dc)



# All persisted user options. Keep names stable — they're written to JSON.
DEFAULT_CONFIG = {
    # ---- Font ----
    "font_family": "Cascadia Mono",
    "font_size": 140,
    "font_weight": "bold",         # "normal" | "bold"

    # ---- Time format ----
    "leading_zero": True,
    "hour_format_24": True,
    "show_seconds": True,
    "show_ampm": True,             # only used when 12-hour is on

    # ---- Spacing ----
    "digit_spacing": 4,            # extra pixels between digits
    "separator_spacing": 6,        # extra pixels on each side of separators
    "separator_style": "colon",    # colon | dots | dash | none
    "separator_dot_radius_pct": 12,  # % of font size; for dots / colon round dots
    "separator_y_offset_pct": 0,   # % of font size; +down -up. 0 = visually centered
    "separator_circle": True,      # force colon/dots to be perfect circles

    # ---- Text colors ----
    "color": "#FFFFFF",
    "color_alpha": 1.0,            # opacity of the digit color
    "sep_color": "#FFFFFF",        # separator "on" color
    "sep_color_alpha": 1.0,        # opacity of the separator color

    # ---- Text outline & shadow ----
    "text_outline_enabled": False,
    "text_outline_color": "#000000",
    "text_outline_thickness": 2,
    "text_shadow_enabled": False,
    "text_shadow_color": "#000000",
    "text_shadow_offset_x": 4,
    "text_shadow_offset_y": 4,
    "text_shadow_blur": 6,
    "text_shadow_alpha": 0.6,

    # ---- Blink ----
    "blink_interval_ms": 600,      # full period between state changes; 0 = no blink
    "blink_anim_ms": 150,          # how long the fade between on/off colors lasts
    "blink_color_off": "#888888",  # color of separator (and optionally digits) when "off"
    "blink_applies_to_digits": False,  # if True, the whole clock blinks; else only separators

    # ---- Box (background panel) ----
    "box_enabled": False,
    "box_color": "#000000",
    "bg_alpha": 0.4,
    # Inner padding can be negative — useful when a font has built-in vertical
    # padding (e.g. tall ascender/descender room) and you want the box to hug
    # the visible glyphs more tightly.
    "box_padding_inner_x": 24,
    "box_padding_inner_y": 12,
    "box_padding_outer_x": 0,
    "box_padding_outer_y": 0,
    "box_corner_radius": 18,
    "box_outline_enabled": False,
    "box_outline_color": "#FFFFFF",
    "box_outline_thickness": 2,
    "box_shadow_enabled": False,
    "box_shadow_color": "#000000",
    "box_shadow_offset_x": 6,
    "box_shadow_offset_y": 6,
    "box_shadow_blur": 12,
    "box_shadow_alpha": 0.5,

    # ---- Date (rendered above or below the time, inside the same box) ----
    "date_enabled": False,
    # strftime format. The Settings dialog offers common presets; this
    # field is also free-text for power users.
    "date_format": "%A, %d %B %Y",   # "Monday, 01 January 2026"
    # Empty string -> inherit from font_family
    "date_font_family": "",
    "date_font_weight": "normal",
    # Pixel size of the date font. Ignored when date_stretch_to_time is on.
    "date_font_size": 40,
    "date_color": "#FFFFFF",
    "date_color_alpha": 1.0,
    # "below" or "above" — where the date row sits relative to the time
    "date_position": "below",
    # Pixel gap between the time row and the date row. Negative values pull
    # them together; very negative will cause them to overlap (useful when
    # a font has built-in ascender/descender room you want to claw back).
    "date_gap": 10,
    # Horizontal alignment of the date relative to the time block:
    # "left", "center", "right"
    "date_align": "center",
    # Fine adjustment on top of alignment, in pixels. Positive = right.
    "date_offset_x": 0,
    # When True, ignore date_font_size and pick a font size that makes the
    # date span the same width as the time (no glyph deformation; the
    # rendered text grows or shrinks proportionally).
    "date_stretch_to_time": False,
    # Extra horizontal space between characters in the date.
    "date_letter_spacing": 0,

    # ---- Calendar (popup on hover) ----
    "calendar_enabled": True,
    "calendar_hover_delay_ms": 3000,    # hover this long before opening
    # How long the cursor must stay outside both the clock and the calendar
    # before the popup dismisses. Gives the user a moment to move the
    # cursor past the calendar without it disappearing.
    "calendar_dismiss_delay_ms": 800,
    # 9-direction expansion: which corner/edge of the calendar attaches to
    # the clock box. e.g. "expand-down" puts the calendar BELOW the clock,
    # "expand-left" puts it to the LEFT, "expand-down-right" puts it to the
    # bottom-right of the clock.
    "calendar_expand": "expand-down",
    "calendar_offset": 12,              # pixels between calendar and clock
    "calendar_hide_time": False,        # hide the clock while calendar open
    # Layout
    "calendar_font_family": "",         # blank -> inherit clock font
    "calendar_font_size": 18,
    "calendar_font_weight": "normal",
    "calendar_cell_padding_x": 6,       # horiz padding inside each date cell
    "calendar_cell_padding_y": 4,
    "calendar_row_spacing": 2,          # vert gap between rows
    "calendar_col_spacing": 2,          # horiz gap between columns
    "calendar_digit_spacing": 0,        # px between digits within one date
    "calendar_leading_zero": False,     # if False, center-align single digits
    # Week
    "calendar_week_starts_on": "monday",  # "monday" or "sunday"
    "calendar_weekend_days": "sat-sun",   # "sat-sun", "sun-only", "fri-sat", "none"
    "calendar_highlight_weekend": True,
    "calendar_weekend_highlight_mode": "background",  # "background" or "foreground"
    "calendar_weekend_color": "#3a2030",
    "calendar_weekend_color_alpha": 1.0,
    # Colors
    "calendar_color": "#FFFFFF",        # default date text color
    "calendar_color_alpha": 1.0,
    "calendar_today_color": "#FFD24A",  # highlight color for today's cell
    "calendar_today_color_alpha": 1.0,
    "calendar_other_month_color": "#666666",  # adjacent-month dates
    "calendar_other_month_color_alpha": 0.7,
    "calendar_header_color": "#FFD24A",  # month/year header + weekday names
    "calendar_header_color_alpha": 1.0,
    "calendar_bg_color": "#101010",
    "calendar_bg_alpha": 0.95,
    # Box
    "calendar_box_rounded": True,
    "calendar_box_corner_radius": 14,
    "calendar_box_outline_enabled": False,
    "calendar_box_outline_color": "#FFFFFF",
    "calendar_box_outline_thickness": 1,

    "anchor": "top-right",
    "margin_x": 30,
    "margin_y": 30,
    # Saved bounding rect [left, top, right, bottom] of the monitor the
    # clock was on the last time the user moved it or changed anchor. We
    # match this against the live monitor list at startup so the clock
    # comes back to the same screen even after a restart. null on first
    # run; we re-derive it the first time the user touches anything.
    "monitor_rect": None,
    "always_on_top": True,
    "click_through": False,
    "draggable": True,
    "autostart": False,
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    raw = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    cfg.update(raw)
    # ---- Migrations from older versions ----
    # v2.x had a single font_alpha; map it onto the digit + separator alphas
    # if those aren't already explicitly set in the saved file.
    if "font_alpha" in raw:
        a = float(raw["font_alpha"])
        for k in ("color_alpha", "sep_color_alpha"):
            if k not in raw:
                cfg[k] = a
    # Drop any keys not in defaults (forward compatibility cleanup;
    # also discards old adaptive_color settings from previous versions)
    return {k: cfg.get(k, DEFAULT_CONFIG[k]) for k in DEFAULT_CONFIG}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Failed to save config: {e}")


# ---------------------------------------------------------------------------
# Single instance
# ---------------------------------------------------------------------------
class SingleInstance:
    def __init__(self, name="DateClock_SingleInstance_Mutex"):
        self.mutex = None
        self.already_running = False
        k = ctypes.windll.kernel32
        self.mutex = k.CreateMutexW(None, False, name)
        if k.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            self.already_running = True

    def release(self):
        if self.mutex:
            ctypes.windll.kernel32.CloseHandle(self.mutex)
            self.mutex = None


# ---------------------------------------------------------------------------
# Autostart
# ---------------------------------------------------------------------------
def get_executable_path():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'


def set_autostart(enable):
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ,
                                  get_executable_path())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"Autostart error: {e}")
        return False


def is_autostart_enabled():
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c*2 for c in h)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(c))) for c in rgb))


def perceived_brightness(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    return rgb_to_hex((lerp(r1, r2, t), lerp(g1, g2, t), lerp(b1, b2, t)))


# ---------------------------------------------------------------------------
# Pillow font cache (loading a TTF every frame would crush perf)
# ---------------------------------------------------------------------------
_font_cache = {}
_font_registry_cache = None   # full registry mapping, loaded lazily
_font_file_cache = None       # normalized {display_name: path}


def _load_windows_font_registry():
    """
    Read both HKLM and HKCU font registries.

    Windows stores installed fonts as values like:
        "Consolas (TrueType)"               -> "consola.ttf"
        "Consolas Bold (TrueType)"          -> "consolab.ttf"
        "Segoe UI (TrueType)"               -> "segoeui.ttf"
        "Cascadia Mono Regular (TrueType)"  -> "CascadiaMono.ttf"
    Each entry's value is either just a filename (in %WINDIR%\\Fonts) or
    an absolute path (for per-user fonts). Returns a list of
    (display_name, file_path) tuples.
    """
    global _font_registry_cache
    if _font_registry_cache is not None:
        return _font_registry_cache

    try:
        import winreg
    except ImportError:
        _font_registry_cache = []
        return _font_registry_cache

    entries = []
    locations = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    ]
    system_fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as k:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if not value:
                        continue
                    # Strip the "(TrueType)" / "(OpenType)" suffix
                    display = name
                    for tag in (" (TrueType)", " (OpenType)",
                                " (All res)", " (VFAT)"):
                        if display.endswith(tag):
                            display = display[: -len(tag)]
                            break
                    p = Path(value)
                    if not p.is_absolute():
                        p = system_fonts_dir / value
                    entries.append((display.strip(), p))
        except OSError:
            continue

    _font_registry_cache = entries
    return entries


def _build_font_file_cache():
    """Build {normalized_family_name: list_of_paths_with_variant_tags}."""
    global _font_file_cache
    if _font_file_cache is not None:
        return _font_file_cache

    entries = _load_windows_font_registry()
    table = {}  # family_key -> list of (display_name, path)
    for display, path in entries:
        # Skip if file doesn't actually exist on disk
        try:
            if not path.exists():
                continue
        except OSError:
            continue
        # Many registry entries are "Family Variant1 & Variant2" — for the
        # mapping we want the *base family*. Use the full display name as
        # the key, plus a stripped-down family key.
        key = display.lower().strip()
        table.setdefault(key, []).append((display, path))

    _font_file_cache = table
    return table


def _find_system_font_file(family, weight):
    """
    Resolve a Tk font family name to an actual TTF/TTC file on disk.

    Strategy:
      1. Look for "<family>" in the registry as-is.
      2. Look for "<family> Bold" / "<family> Regular" depending on weight.
      3. Look for any registry entry that *starts with* "<family>".
      4. As a last resort, scan %WINDIR%\\Fonts for filenames that look like
         a match (handles fonts not registered, rare).
    """
    table = _build_font_file_cache()
    fam = family.strip()
    fam_l = fam.lower()
    bold = (weight == "bold")

    def pick_best(matches):
        """Among a list of (display, path), prefer the requested weight."""
        if not matches:
            return None
        scored = []
        for display, path in matches:
            d = display.lower()
            score = 0
            has_bold = ("bold" in d) or d.endswith(" bd")
            has_italic = ("italic" in d) or ("oblique" in d)
            if bold and has_bold:
                score += 10
            if not bold and not has_bold:
                score += 5
            if has_italic:
                score -= 8
            # Exact base name match preferred
            if d == fam_l:
                score += 20
            if d == fam_l + " regular":
                score += 15
            if d == fam_l + " bold":
                score += 15 if bold else -2
            scored.append((score, path))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    # 1. Direct hits (including a "Bold" variant if requested)
    candidates = []
    for key, items in table.items():
        if key == fam_l:
            candidates.extend(items)
        elif bold and key == fam_l + " bold":
            candidates.extend(items)
        elif not bold and key == fam_l + " regular":
            candidates.extend(items)

    if candidates:
        best = pick_best(candidates)
        if best:
            return best

    # 2. "starts with family" — catches e.g. "Cascadia Mono Light" when user
    # asked for "Cascadia Mono"
    candidates = []
    for key, items in table.items():
        if key.startswith(fam_l + " ") or key == fam_l:
            candidates.extend(items)
    if candidates:
        best = pick_best(candidates)
        if best:
            return best

    # 3. Loose substring on registry display names
    candidates = []
    for key, items in table.items():
        if fam_l in key:
            candidates.extend(items)
    if candidates:
        best = pick_best(candidates)
        if best:
            return best

    # 4. Last resort: filename scan (in case registry doesn't have it)
    fam_norm = fam_l.replace(" ", "")
    for base_dir in (Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                     Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" /
                     "Windows" / "Fonts"):
        if not base_dir.exists():
            continue
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            for p in base_dir.glob(ext):
                if fam_norm in p.stem.lower().replace(" ", ""):
                    return p

    return None


# Track what we actually loaded, for the diagnostic in Settings
_font_resolution_log = {}


def get_pillow_font(family, size, weight):
    key = (family, int(size), weight)
    if key in _font_cache:
        return _font_cache[key]

    path = _find_system_font_file(family, weight)
    resolved_via = "registry"
    try:
        if path is not None:
            font = ImageFont.truetype(str(path), int(size))
            _font_resolution_log[(family, weight)] = ("found", str(path))
        else:
            # Try Pillow's own resolver
            try:
                font = ImageFont.truetype(family, int(size))
                resolved_via = "pillow-name"
                _font_resolution_log[(family, weight)] = ("pillow-name", family)
            except Exception:
                # Final fallback: a default TTF we *know* scales
                # Try DejaVuSans bundled with Pillow first
                try:
                    font = ImageFont.truetype("DejaVuSans.ttf", int(size))
                    _font_resolution_log[(family, weight)] = ("fallback-dejavu", "DejaVuSans.ttf")
                except Exception:
                    # Last resort — the bitmap default font. It IGNORES size.
                    font = ImageFont.load_default()
                    _font_resolution_log[(family, weight)] = ("BITMAP-DEFAULT (size ignored!)", "")
    except Exception as e:
        font = ImageFont.load_default()
        _font_resolution_log[(family, weight)] = (f"error: {e}", "")
    _font_cache[key] = font
    return font


# ---------------------------------------------------------------------------
# Clock rendering with Pillow
# ---------------------------------------------------------------------------
class ClockRenderer:
    """
    Produces a Pillow RGBA image of the clock given the current config and
    the colors to use for "digit color" and "separator color" (which can
    differ during a blink animation).
    """

    def __init__(self, cfg):
        self.cfg = cfg

    # Geometry of one glyph -------------------------------------------------
    def _glyph_bbox(self, font, ch):
        # textbbox returns the inked bounding box on a temp draw.
        img = Image.new("L", (1, 1))
        d = ImageDraw.Draw(img)
        return d.textbbox((0, 0), ch, font=font)  # (l, t, r, b)

    def _font_metrics(self, font):
        # Use ascent+descent for line height; cap height approximated from "0"
        try:
            ascent, descent = font.getmetrics()
            line_h = ascent + descent
        except Exception:
            ascent = font.size
            line_h = font.size
            descent = 0
        # x-height surrogate using "0" inked bounds
        bb = self._glyph_bbox(font, "0")
        cap_top = bb[1]
        cap_bot = bb[3]
        return ascent, descent, line_h, cap_top, cap_bot

    # Token list build ------------------------------------------------------
    def _build_tokens(self, time_text):
        """Split the time string into a list of (kind, text) tokens.
        kind ∈ {'digit', 'sep', 'space', 'ampm'}"""
        tokens = []
        for ch in time_text:
            if ch.isdigit():
                tokens.append(("digit", ch))
            elif ch in (":", ".", "·"):
                tokens.append(("sep", ch))
            elif ch == " ":
                tokens.append(("space", ch))
            else:
                tokens.append(("ampm", ch))
        return tokens

    def format_time_string(self):
        cfg = self.cfg
        now = datetime.now()
        if cfg["hour_format_24"]:
            h = now.hour
            suffix = ""
        else:
            h = now.hour % 12 or 12
            if cfg.get("show_ampm", True):
                suffix = " " + ("AM" if now.hour < 12 else "PM")
            else:
                suffix = ""

        hh = f"{h:02d}" if cfg["leading_zero"] else f"{h}"
        m = f"{now.minute:02d}"
        s = f"{now.second:02d}"
        if cfg["show_seconds"]:
            return f"{hh}:{m}:{s}{suffix}"
        return f"{hh}:{m}{suffix}"

    def _date_text(self):
        cfg = self.cfg
        fmt = cfg.get("date_format", "%A, %d %B %Y")
        try:
            return datetime.now().strftime(fmt)
        except Exception:
            # Bad format string — fall back to a safe default rather than
            # crashing the renderer.
            return datetime.now().strftime("%A, %d %B %Y")

    def _date_font_family(self):
        cfg = self.cfg
        fam = cfg.get("date_font_family", "")
        return fam if fam else cfg["font_family"]

    def _measure_date_string(self, font, text, letter_spacing):
        """Width of `text` rendered with `font` and the given inter-character
        spacing. Height is the font's line height. Returns (w, h, ascent)."""
        if not text:
            return (0, 0, 0)
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        if letter_spacing == 0:
            # Fast path: native length
            try:
                bbox = font.getbbox(text)
                return (bbox[2] - bbox[0], line_h, ascent)
            except Exception:
                pass
        # Per-character path (slower but supports letter spacing)
        total = 0
        for i, ch in enumerate(text):
            try:
                bbox = font.getbbox(ch)
                w = bbox[2] - bbox[0]
            except Exception:
                w = 0
            total += w
            if i < len(text) - 1:
                total += letter_spacing
        return (total, line_h, ascent)

    def _pick_date_font_size_for_width(self, target_w, family, weight,
                                        letter_spacing, text,
                                        lo=8, hi=400):
        """Binary search for the largest font size whose rendered text width
        is <= target_w. Used for date_stretch_to_time."""
        if target_w <= 0 or not text:
            return lo
        best = lo
        while lo <= hi:
            mid = (lo + hi) // 2
            f = get_pillow_font(family, mid, weight)
            w, _, _ = self._measure_date_string(f, text, letter_spacing)
            if w <= target_w:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _resolve_date_block(self, time_width):
        """Decide the date string, font, and final dimensions. Returns
        a dict with: enabled, text, font, width, height, ascent, color, alpha
        or None if disabled."""
        cfg = self.cfg
        if not cfg.get("date_enabled", False):
            return None
        text = self._date_text()
        if not text:
            return None

        family = self._date_font_family()
        weight = cfg.get("date_font_weight", "normal")
        letter_spacing = int(cfg.get("date_letter_spacing", 0))

        if cfg.get("date_stretch_to_time", False) and time_width > 0:
            size = self._pick_date_font_size_for_width(
                time_width, family, weight, letter_spacing, text,
                lo=8, hi=max(8, int(cfg["font_size"] * 2)),
            )
        else:
            size = int(cfg.get("date_font_size", 40))
        size = max(6, size)

        font = get_pillow_font(family, size, weight)
        w, h, ascent = self._measure_date_string(font, text, letter_spacing)
        return {
            "text": text,
            "font": font,
            "width": w,
            "height": h,
            "ascent": ascent,
            "letter_spacing": letter_spacing,
            "color": cfg.get("date_color", "#FFFFFF"),
            "alpha": float(cfg.get("date_color_alpha", 1.0)),
            "align": cfg.get("date_align", "center"),
            "offset_x": int(cfg.get("date_offset_x", 0)),
            "size": size,
        }

    def _draw_date_string(self, img, block, time_left, time_w, y_top):
        """Render the resolved date block onto img. (time_left, time_w) is the
        time's horizontal extent; the date is aligned relative to it."""
        if not block:
            return
        # Horizontal alignment within the time's footprint
        align = block["align"]
        if align == "left":
            x = time_left
        elif align == "right":
            x = time_left + time_w - block["width"]
        else:
            x = time_left + (time_w - block["width"]) // 2
        x += block["offset_x"]

        fill = self._rgba(block["color"], block["alpha"])
        font = block["font"]
        text = block["text"]
        letter_spacing = block["letter_spacing"]

        d = ImageDraw.Draw(img)
        if letter_spacing == 0:
            # Fast path: single text() call
            d.text((int(round(x)), int(round(y_top))), text,
                   font=font, fill=fill)
            return
        # Slow path: one character at a time
        cx = x
        for i, ch in enumerate(text):
            try:
                bbox = font.getbbox(ch)
                cw = bbox[2] - bbox[0]
            except Exception:
                cw = 0
            d.text((int(round(cx)), int(round(y_top))), ch,
                   font=font, fill=fill)
            cx += cw + letter_spacing

    # Main rendering --------------------------------------------------------
    def render(self, digit_color, sep_color,
               digit_alpha=1.0, sep_alpha=1.0):
        """Return PIL.Image RGBA of the current time.

        Colors are hex strings. Alpha values 0..1 are applied per-color
        (digits and separator independently) so the box and shadows are
        unaffected.
        """
        cfg = self.cfg
        time_text = self.format_time_string()
        tokens = self._build_tokens(time_text)

        font = get_pillow_font(cfg["font_family"], cfg["font_size"],
                               cfg["font_weight"])
        ascent, descent, line_h, cap_top, cap_bot = self._font_metrics(font)

        digit_spacing = int(cfg["digit_spacing"])
        sep_spacing = int(cfg["separator_spacing"])

        # Bake per-color opacity into RGBA tuples that Pillow accepts as fill
        digit_fill = self._rgba(digit_color, digit_alpha)
        sep_fill = self._rgba(sep_color, sep_alpha)

        # Pre-measure widths
        token_widths = []
        for kind, ch in tokens:
            if kind == "sep":
                w = self._separator_width(font, ch)
            else:
                bb = self._glyph_bbox(font, ch)
                w = bb[2] - bb[0]
            token_widths.append(w)

        # Total time-row width
        total_w = 0
        for i, (kind, ch) in enumerate(tokens):
            total_w += token_widths[i]
            if i < len(tokens) - 1:
                next_kind = tokens[i + 1][0]
                if kind == "sep" or next_kind == "sep":
                    total_w += sep_spacing
                else:
                    total_w += digit_spacing
        time_w = total_w
        time_h = int(line_h)

        # ---- Date block ----
        # Resolve the date once: text, font, width, height. None if disabled.
        date_block = self._resolve_date_block(time_w)
        if date_block is not None:
            date_gap = int(cfg.get("date_gap", 10))
            content_w = max(time_w, date_block["width"])
            # Allow negative gap so the date can overlap into the time row's
            # vertical padding. But guard against pathological values that
            # would make content_h zero or negative.
            content_h = max(time_h, time_h + date_gap + date_block["height"])
        else:
            date_gap = 0
            content_w = time_w
            content_h = time_h

        # Outline & shadow extra padding around text (kept independent of
        # box padding so users can have a tight box with a soft shadow)
        text_pad = 0
        if cfg["text_outline_enabled"]:
            text_pad = max(text_pad, int(cfg["text_outline_thickness"]) + 2)
        if cfg["text_shadow_enabled"]:
            text_pad = max(
                text_pad,
                abs(int(cfg["text_shadow_offset_x"])) + int(cfg["text_shadow_blur"]) + 2,
                abs(int(cfg["text_shadow_offset_y"])) + int(cfg["text_shadow_blur"]) + 2,
            )

        # Box paddings (allowing negative for tighter hugs around fonts with
        # built-in vertical room)
        if cfg["box_enabled"]:
            box_pad_x = int(cfg["box_padding_inner_x"])
            box_pad_y = int(cfg["box_padding_inner_y"])
            box_outer_x = max(0, int(cfg["box_padding_outer_x"]))
            box_outer_y = max(0, int(cfg["box_padding_outer_y"]))
            box_outline_t = (int(cfg["box_outline_thickness"])
                             if cfg["box_outline_enabled"] else 0)
        else:
            box_pad_x = box_pad_y = box_outer_x = box_outer_y = 0
            box_outline_t = 0

        # Box shadow contributes to canvas size too
        if cfg["box_enabled"] and cfg["box_shadow_enabled"]:
            shadow_extra_x = (abs(int(cfg["box_shadow_offset_x"]))
                              + int(cfg["box_shadow_blur"]) + 2)
            shadow_extra_y = (abs(int(cfg["box_shadow_offset_y"]))
                              + int(cfg["box_shadow_blur"]) + 2)
        else:
            shadow_extra_x = shadow_extra_y = 0

        # If inner padding is negative the box will be smaller than the text;
        # the canvas still has to be at least as big as the text bounds so we
        # don't clip glyphs. Use max(text_extent, text_extent + 2*box_pad).
        text_extent_w = content_w + 2 * text_pad
        text_extent_h = content_h + 2 * text_pad
        box_inner_w = text_extent_w + 2 * box_pad_x
        box_inner_h = text_extent_h + 2 * box_pad_y
        canvas_inner_w = max(text_extent_w, box_inner_w)
        canvas_inner_h = max(text_extent_h, box_inner_h)

        canvas_w = (canvas_inner_w + 2 * box_outline_t
                    + 2 * box_outer_x + 2 * shadow_extra_x)
        canvas_h = (canvas_inner_h + 2 * box_outline_t
                    + 2 * box_outer_y + 2 * shadow_extra_y)
        canvas_w = max(2, int(canvas_w))
        canvas_h = max(2, int(canvas_h))

        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

        # The content rectangle (time + optional date) sits centered in the
        # canvas. The box surrounds it, expanded by box_pad on each side.
        content_left = ((canvas_w - content_w) // 2)
        content_top = ((canvas_h - content_h) // 2)
        # Where the time row sits: centered horizontally within content_w
        time_left = content_left + (content_w - time_w) // 2
        # Vertical position depends on date_position. When the date is on
        # top, the time sits below it; otherwise time stays at the top.
        date_position = cfg.get("date_position", "below")
        if date_block is not None and date_position == "above":
            time_top = content_top + date_block["height"] + date_gap
            date_top = content_top
        else:
            time_top = content_top
            date_top = (content_top + time_h + date_gap
                        if date_block is not None else None)

        # Box geometry derived from the content rectangle + padding
        text_extent_left = content_left - text_pad
        text_extent_top = content_top - text_pad
        text_extent_right = content_left + content_w + text_pad
        text_extent_bottom = content_top + content_h + text_pad
        box_left = text_extent_left - box_pad_x - box_outline_t
        box_top = text_extent_top - box_pad_y - box_outline_t
        box_right = text_extent_right + box_pad_x + box_outline_t
        box_bottom = text_extent_bottom + box_pad_y + box_outline_t

        # ---- Box shadow ----
        if cfg["box_enabled"] and cfg["box_shadow_enabled"]:
            self._draw_box_shadow(img, (box_left, box_top, box_right, box_bottom))

        # ---- Box fill + outline ----
        if cfg["box_enabled"]:
            self._draw_box(img, (box_left, box_top, box_right, box_bottom))

        # Vertical baseline of the time row
        baseline_y = time_top + (time_h - (cap_bot - cap_top)) / 2 - cap_top

        # ---- Text shadow for time (separate pass, blurred) ----
        if cfg["text_shadow_enabled"]:
            shadow_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            sa = max(0.0, min(1.0, float(cfg["text_shadow_alpha"])))
            shadow_fill = self._rgba(cfg["text_shadow_color"], sa)
            self._draw_tokens(
                shadow_img,
                tokens, token_widths, font,
                start_x=time_left + int(cfg["text_shadow_offset_x"]),
                baseline_y=baseline_y + int(cfg["text_shadow_offset_y"]),
                digit_fill=shadow_fill,
                sep_fill=shadow_fill,
                draw_outline=False,
            )
            blur = max(0, int(cfg["text_shadow_blur"]))
            if blur > 0:
                shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(blur))
            img.alpha_composite(shadow_img)

        # ---- Main time text ----
        self._draw_tokens(
            img,
            tokens, token_widths, font,
            start_x=time_left,
            baseline_y=baseline_y,
            digit_fill=digit_fill,
            sep_fill=sep_fill,
            draw_outline=cfg["text_outline_enabled"],
        )

        # ---- Date row ----
        if date_block is not None:
            # date_top was computed above based on date_position
            self._draw_date_string(img, date_block, time_left, time_w,
                                   date_top)

        return img

    # Convert "#RRGGBB" + alpha 0..1 to (r,g,b,a) tuple Pillow understands
    def _rgba(self, hex_color, alpha):
        r, g, b = hex_to_rgb(hex_color)
        a = int(max(0.0, min(1.0, float(alpha))) * 255)
        return (r, g, b, a)

    # Drawing helpers -------------------------------------------------------
    def _separator_width(self, font, ch):
        cfg = self.cfg
        style = cfg["separator_style"]
        if style == "none":
            return 0
        if style in ("colon", "dots"):
            r = max(1, int(cfg["font_size"] * cfg["separator_dot_radius_pct"] / 100))
            return r * 2
        if style == "dash":
            bb = self._glyph_bbox(font, "-")
            return bb[2] - bb[0]
        return 0

    def _draw_tokens(self, img, tokens, widths, font, start_x, baseline_y,
                     digit_fill, sep_fill, draw_outline):
        cfg = self.cfg
        x = start_x
        digit_spacing = int(cfg["digit_spacing"])
        sep_spacing = int(cfg["separator_spacing"])

        for i, (kind, ch) in enumerate(tokens):
            w = widths[i]
            if kind == "digit" or kind == "ampm":
                self._draw_glyph(img, ch, font, x, baseline_y, digit_fill,
                                 draw_outline=draw_outline)
            elif kind == "sep":
                self._draw_separator(img, ch, font, x, baseline_y,
                                     sep_fill, draw_outline)
            x += w
            if i < len(tokens) - 1:
                next_kind = tokens[i + 1][0]
                if kind == "sep" or next_kind == "sep":
                    x += sep_spacing
                else:
                    x += digit_spacing

    def _draw_glyph(self, img, ch, font, x, baseline_y, fill_rgba,
                    draw_outline):
        """Draw one character directly onto the target image. No resampling
        anywhere — that's what was producing stray pixels."""
        cfg = self.cfg
        bb = self._glyph_bbox(font, ch)
        # Drawing position: x is where the inked bbox left edge should land
        draw_x = int(round(x - bb[0]))
        draw_y = int(round(baseline_y))
        d = ImageDraw.Draw(img)
        if draw_outline:
            outline_rgba = self._rgba(cfg["text_outline_color"], 1.0)
            d.text((draw_x, draw_y), ch, font=font, fill=fill_rgba,
                   stroke_width=max(0, int(cfg["text_outline_thickness"])),
                   stroke_fill=outline_rgba)
        else:
            d.text((draw_x, draw_y), ch, font=font, fill=fill_rgba)

    def _draw_separator(self, img, ch, font, x, baseline_y, fill_rgba,
                        draw_outline):
        cfg = self.cfg
        style = cfg["separator_style"]
        if style == "none":
            return

        ascent, descent, line_h, cap_top, cap_bot = self._font_metrics(font)
        cap_h = cap_bot - cap_top
        cap_center_y = baseline_y + (cap_top + cap_bot) / 2
        y_offset = cfg["separator_y_offset_pct"] / 100.0 * cfg["font_size"]
        cap_center_y += y_offset

        if style == "dash":
            self._draw_glyph(img, "-", font, x, baseline_y, fill_rgba,
                             draw_outline=draw_outline)
            return

        r = max(1, int(cfg["font_size"] * cfg["separator_dot_radius_pct"] / 100))
        circle = cfg["separator_circle"]
        if style == "colon":
            spacing = cap_h * 0.45
            centers_y = [cap_center_y - spacing / 2, cap_center_y + spacing / 2]
        else:  # dots
            centers_y = [cap_center_y]

        d = ImageDraw.Draw(img)
        outline_rgba = self._rgba(cfg["text_outline_color"], 1.0)
        outline_w = (max(1, int(cfg["text_outline_thickness"]))
                     if draw_outline else 0)
        for cy in centers_y:
            cx = x + r
            bbox = (cx - r, cy - r, cx + r, cy + r)
            if circle:
                d.ellipse(bbox, fill=fill_rgba,
                          outline=(outline_rgba if outline_w > 0 else None),
                          width=outline_w if outline_w > 0 else 1)
            else:
                d.rectangle(bbox, fill=fill_rgba,
                            outline=(outline_rgba if outline_w > 0 else None),
                            width=outline_w if outline_w > 0 else 1)

    def _draw_box(self, img, rect):
        cfg = self.cfg
        l, t, r, b = rect
        radius = max(0, int(cfg["box_corner_radius"]))
        # Fill
        fill_rgb = hex_to_rgb(cfg["box_color"])
        fill_a = int(max(0.0, min(1.0, float(cfg["bg_alpha"]))) * 255)
        if fill_a > 0:
            self._rounded_rect(img, l, t, r, b, radius,
                               fill=(*fill_rgb, fill_a))
        # Outline
        if cfg["box_outline_enabled"]:
            self._rounded_rect(img, l, t, r, b, radius,
                               outline=cfg["box_outline_color"],
                               width=max(1, int(cfg["box_outline_thickness"])))

    def _draw_box_shadow(self, img, rect):
        cfg = self.cfg
        l, t, r, b = rect
        radius = max(0, int(cfg["box_corner_radius"]))
        blur = max(0, int(cfg["box_shadow_blur"]))
        off_x = int(cfg["box_shadow_offset_x"])
        off_y = int(cfg["box_shadow_offset_y"])
        sa = max(0.0, min(1.0, float(cfg["box_shadow_alpha"])))

        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        rgb = hex_to_rgb(cfg["box_shadow_color"])
        a = int(sa * 255)
        self._rounded_rect(shadow,
                           l + off_x, t + off_y, r + off_x, b + off_y,
                           radius, fill=(*rgb, a))
        if blur > 0:
            shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
        img.alpha_composite(shadow)

    def _rounded_rect(self, img, l, t, r, b, radius, fill=None, outline=None, width=1):
        d = ImageDraw.Draw(img)
        # Pillow has rounded_rectangle since 8.2
        try:
            d.rounded_rectangle((l, t, r, b), radius=radius,
                                fill=fill, outline=outline, width=width)
        except AttributeError:
            # Fallback: regular rectangle
            d.rectangle((l, t, r, b), fill=fill, outline=outline, width=width)


# ---------------------------------------------------------------------------
# Blink color state machine (interval + animation duration are independent)
# ---------------------------------------------------------------------------
class BlinkState:
    """
    Tracks a square-wave 'on/off' state that flips every blink_interval_ms.
    Between flips it produces a smooth eased interpolation from previous to
    new value over blink_anim_ms milliseconds.
    """

    def __init__(self):
        self._is_on = True
        self._last_flip = time.monotonic()
        self._anim_start = self._last_flip - 10  # past, so initial state is settled

    def update(self, interval_ms, anim_ms):
        now = time.monotonic()
        if interval_ms <= 0:
            self._is_on = True
            return 1.0, True  # fully on, target on
        if (now - self._last_flip) * 1000 >= interval_ms:
            self._last_flip = now
            self._anim_start = now
            self._is_on = not self._is_on
        anim_ms = max(1, anim_ms)
        t = min(1.0, (now - self._anim_start) * 1000 / anim_ms)
        # Ease-in-out (cosine)
        eased = 0.5 - 0.5 * math.cos(math.pi * t)
        return eased, self._is_on


# ---------------------------------------------------------------------------
# Clock window
# ---------------------------------------------------------------------------
class ClockWindow:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", cfg["always_on_top"])

        # We render the clock with Pillow and push the RGBA pixels straight
        # to the OS via UpdateLayeredWindow, so Windows composites the
        # antialiased edges against the actual desktop. No chroma key, no
        # fringe.
        #
        # Tk still owns the HWND (for events, dragging, sizing), but its own
        # drawing is invisible behind the layered surface. We give it a 1x1
        # dummy canvas just so the widget tree is happy.
        self.canvas = tk.Canvas(self.root, width=1, height=1,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._last_render_size = (0, 0)
        self._layered_ready = False

        self.renderer = ClockRenderer(cfg)
        self.blink = BlinkState()

        self._dragging = False
        self._drag_dx = 0
        self._drag_dy = 0

        self._bind_drag()
        # The layered-window style must be applied before the first paint.
        self.root.after(0, self._init_layered_window)
        self.root.after(10, self.apply_config)
        self.root.after(20, self._tick)
        # Re-assert topmost z-order periodically. Tk's -topmost attribute
        # gets dropped silently by Windows in various situations (UAC,
        # fullscreen apps, sleep/resume), and a single SetWindowPos call
        # at toggle-time doesn't survive those. So we just keep asserting.
        self.root.after(1000, self._reassert_topmost)

        # Calendar popup state. We poll the global cursor position because
        # Tk's <Enter>/<Motion> events don't fire when click-through is on
        # (the OS routes the cursor past our window).
        self.calendar = CalendarPopup(self)
        self._hover_started_at = None
        self._cursor_currently_inside = False
        # When the cursor leaves both the clock and the calendar, we record
        # the time it left. The popup only dismisses after the cursor has
        # been outside for `calendar_dismiss_delay_ms`. If it re-enters in
        # that window, the timer is cancelled.
        self._cursor_left_at = None
        self._hidden = False
        self.root.after(200, self._poll_hover)

    def _init_layered_window(self):
        """One-time setup: ensure WS_EX_LAYERED is on so UpdateLayeredWindow
        works, and reflect any user toggles for click-through / no-activate."""
        hwnd = self._get_hwnd()
        if not hwnd:
            self.root.after(20, self._init_layered_window)
            return
        try:
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            if self.cfg.get("click_through", False):
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            self._layered_ready = True
        except Exception:
            pass

    def _get_hwnd(self):
        try:
            # Tk's winfo_id returns the child HWND; we want the toplevel.
            child = self.root.winfo_id()
            parent = ctypes.windll.user32.GetParent(child)
            return parent if parent else child
        except Exception:
            return 0

    def _reassert_topmost(self):
        """Re-issue HWND_TOPMOST every second so we stay on top across
        events that silently drop the topmost z-order (UAC prompts,
        fullscreen apps grabbing focus, resume from sleep, etc.)."""
        try:
            if self.cfg.get("always_on_top", True):
                hwnd = self._get_hwnd()
                if hwnd:
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_TOPMOST_REASSERT,
                    )
            else:
                # User turned topmost off — push us to non-topmost too so
                # the change is honored even if Tk's -topmost was sticky.
                hwnd = self._get_hwnd()
                if hwnd:
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                        SWP_TOPMOST_REASSERT,
                    )
        except Exception:
            pass
        # Reschedule. 1 second is fine — fast enough to feel persistent,
        # negligible CPU cost.
        self.root.after(1000, self._reassert_topmost)

    # -- Calendar hover detection ------------------------------------------
    def _get_cursor_pos(self):
        try:
            pt = _POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return (pt.x, pt.y)
        except Exception:
            return None

    def _cursor_inside_clock(self, cx, cy):
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        return (x <= cx < x + w) and (y <= cy < y + h)

    def _cursor_inside_calendar(self, cx, cy):
        if not self.calendar.is_open():
            return False
        try:
            top = self.calendar.top
            x = top.winfo_x()
            y = top.winfo_y()
            w = top.winfo_width()
            h = top.winfo_height()
            return (x <= cx < x + w) and (y <= cy < y + h)
        except Exception:
            return False

    def _poll_hover(self):
        try:
            if not self.cfg.get("calendar_enabled", True):
                # Feature off — make sure no popup is lingering
                if self.calendar.is_open():
                    self.calendar.close()
                self._hover_started_at = None
                self._cursor_currently_inside = False
                self.root.after(500, self._poll_hover)
                return

            pos = self._get_cursor_pos()
            if pos is None:
                self.root.after(200, self._poll_hover)
                return
            cx, cy = pos
            in_clock = self._cursor_inside_clock(cx, cy)
            in_calendar = self._cursor_inside_calendar(cx, cy)
            in_combined = in_clock or in_calendar

            if self.calendar.is_open():
                # Cursor is over clock or calendar: keep it open and reset
                # any pending dismiss.
                if in_combined:
                    self._cursor_left_at = None
                else:
                    now = time.monotonic()
                    if self._cursor_left_at is None:
                        # Just left — start the grace timer.
                        self._cursor_left_at = now
                    else:
                        # Already counting; check if the grace period passed.
                        dismiss_ms = int(self.cfg.get(
                            "calendar_dismiss_delay_ms", 800))
                        if (now - self._cursor_left_at) * 1000 >= dismiss_ms:
                            self.calendar.close()
                            self._hover_started_at = None
                            self._cursor_currently_inside = False
                            self._cursor_left_at = None
            else:
                # Tracking entry into the clock for the hover-to-open
                # gesture.
                self._cursor_left_at = None
                if in_clock:
                    now = time.monotonic()
                    if not self._cursor_currently_inside:
                        self._cursor_currently_inside = True
                        self._hover_started_at = now
                    elif self._hover_started_at is not None:
                        delay_ms = int(self.cfg.get(
                            "calendar_hover_delay_ms", 3000))
                        if (now - self._hover_started_at) * 1000 >= delay_ms:
                            self.calendar.open()
                            self._hover_started_at = None
                else:
                    self._cursor_currently_inside = False
                    self._hover_started_at = None
        except Exception:
            pass
        # 100ms polling is responsive without burning CPU
        self.root.after(100, self._poll_hover)

    # -- Visibility (used by the calendar popup if hide_time is on) --------
    def set_hidden(self, hidden):
        if self._hidden == hidden:
            return
        self._hidden = hidden
        # Force a re-render which will apply the alpha=0 image
        self._render_now()

    # -- Drag ---------------------------------------------------------------
    def _bind_drag(self):
        for w in (self.root, self.canvas):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, e):
        if not self.cfg.get("draggable", True):
            return
        # If the calendar is open, dismiss it before starting the drag.
        if self.calendar.is_open():
            self.calendar.close()
        self._dragging = True
        self._drag_dx = e.x_root - self.root.winfo_x()
        self._drag_dy = e.y_root - self.root.winfo_y()

    def _on_drag(self, e):
        if not self._dragging:
            return
        x = e.x_root - self._drag_dx
        y = e.y_root - self._drag_dy
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, e):
        if not self._dragging:
            return
        self._dragging = False
        self._update_margins_from_position()
        save_config(self.cfg)

    # -- Click-through ------------------------------------------------------
    def _apply_click_through(self):
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        if not hwnd:
            return
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if self.cfg.get("click_through", False):
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    # -- Screen geometry (multi-monitor aware) -----------------------------
    def _virtual_screen_bounds(self):
        """Return (left, top, right, bottom) of the full virtual desktop
        (the rectangle spanning every monitor). Falls back to Tk if Win32
        isn't available."""
        try:
            user32 = ctypes.windll.user32
            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79
            x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            return x, y, x + w, y + h
        except Exception:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            return 0, 0, sw, sh

    def _enum_monitors(self):
        """Return a list of (left, top, right, bottom) for every monitor.
        Uses EnumDisplayMonitors via Win32; falls back to the primary."""
        try:
            user32 = ctypes.windll.user32
            monitors = []

            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_int, wintypes_HMONITOR, ctypes.c_void_p,
                ctypes.POINTER(_RECT), ctypes.c_double
            )

            def cb(hMonitor, hdc, lprc, dwData):
                r = lprc.contents
                monitors.append((r.left, r.top, r.right, r.bottom))
                return 1

            user32.EnumDisplayMonitors(0, None, MONITORENUMPROC(cb), 0)
            if monitors:
                return monitors
        except Exception:
            pass
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        return [(0, 0, sw, sh)]

    def _monitor_for_point(self, px, py):
        """Find the monitor rect containing (px, py). Falls back to the
        nearest monitor if the point isn't inside any (e.g. half-dragged)."""
        mons = self._enum_monitors()
        for m in mons:
            l, t, r, b = m
            if l <= px < r and t <= py < b:
                return m
        # Nearest by center distance
        def dist(m):
            cx = (m[0] + m[2]) / 2
            cy = (m[1] + m[3]) / 2
            return (cx - px) ** 2 + (cy - py) ** 2
        return min(mons, key=dist)

    def identify_monitors(self):
        """Pop a big number on each monitor for ~3 seconds — the same idea
        as Windows' built-in 'Identify' button in Display settings."""
        mons = self._enum_monitors()
        overlays = []
        for i, (l, t, r, b) in enumerate(mons, start=1):
            try:
                w = r - l
                h = b - t
                ow = min(360, max(180, w // 4))
                oh = min(360, max(180, h // 4))
                ox = l + (w - ow) // 2
                oy = t + (h - oh) // 2

                top = tk.Toplevel(self.root)
                top.overrideredirect(True)
                top.attributes("-topmost", True)
                try:
                    top.attributes("-alpha", 0.85)
                except tk.TclError:
                    pass
                top.geometry(f"{ow}x{oh}+{ox}+{oy}")
                top.configure(bg="#1F6FEB")
                lbl = tk.Label(top, text=str(i),
                               font=("Segoe UI", min(ow, oh) // 2, "bold"),
                               bg="#1F6FEB", fg="white")
                lbl.pack(fill="both", expand=True)
                overlays.append(top)
            except Exception:
                pass

        def _close():
            for top in overlays:
                try:
                    top.destroy()
                except Exception:
                    pass

        self.root.after(3000, _close)

    def _active_monitor_rect(self):
        """Monitor the clock is currently on. Used while dragging."""
        try:
            self.root.update_idletasks()
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            w = max(1, self.root.winfo_width())
            h = max(1, self.root.winfo_height())
            cx = x + w // 2
            cy = y + h // 2
            return self._monitor_for_point(cx, cy)
        except Exception:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            return (0, 0, sw, sh)

    def _pick_target_monitor(self):
        """Choose which monitor to anchor against. Prefers the one saved in
        config (so the clock returns to the same screen after a restart);
        falls back to the active monitor or the primary if the saved one
        no longer exists. If we fall back, the new choice gets persisted
        so subsequent restarts are consistent."""
        saved = self.cfg.get("monitor_rect")
        mons = self._enum_monitors()
        if saved and len(saved) == 4:
            saved_rect = tuple(int(v) for v in saved)
            # 1. Exact match — same monitor, same position in virtual desktop
            for m in mons:
                if m == saved_rect:
                    return m
            # 2. Approximate match — same size, position within 50 px
            sw_ = saved_rect[2] - saved_rect[0]
            sh_ = saved_rect[3] - saved_rect[1]
            for m in mons:
                mw_ = m[2] - m[0]
                mh_ = m[3] - m[1]
                if (mw_ == sw_ and mh_ == sh_
                        and abs(m[0] - saved_rect[0]) <= 50
                        and abs(m[1] - saved_rect[1]) <= 50):
                    return m
            # 3. No match: same size anywhere
            for m in mons:
                if (m[2] - m[0]) == sw_ and (m[3] - m[1]) == sh_:
                    return m
            # 4. Give up — saved monitor isn't here anymore. Persist the
            # fallback so we don't keep searching for the missing one.
            fallback = self._active_monitor_rect()
            self.cfg["monitor_rect"] = list(fallback)
            save_config(self.cfg)
            return fallback
        return self._active_monitor_rect()

    def _position_from_anchor(self):
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        target = self._pick_target_monitor()
        ml, mt, mr, mb = target
        mw = mr - ml
        mh = mb - mt
        anchor = self.cfg.get("anchor", "top-right")
        mx = int(self.cfg.get("margin_x", 30))
        my = int(self.cfg.get("margin_y", 30))

        if anchor.endswith("left"):
            x = ml + mx
        elif anchor.endswith("right"):
            x = mr - w - mx
        else:
            x = ml + (mw - w) // 2

        if anchor.startswith("top"):
            y = mt + my
        elif anchor.startswith("bottom"):
            y = mb - h - my
        else:
            y = mt + (mh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # First launch (no saved monitor) — record where we landed so the
        # next startup goes to the same screen.
        if self.cfg.get("monitor_rect") is None:
            self.cfg["monitor_rect"] = list(target)
            save_config(self.cfg)

    def _update_margins_from_position(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        active = self._active_monitor_rect()
        ml, mt, mr, mb = active
        anchor = self.cfg.get("anchor", "top-right")

        if anchor.endswith("left"):
            self.cfg["margin_x"] = max(0, x - ml)
        elif anchor.endswith("right"):
            self.cfg["margin_x"] = max(0, mr - x - w)
        else:
            self.cfg["margin_x"] = 0

        if anchor.startswith("top"):
            self.cfg["margin_y"] = max(0, y - mt)
        elif anchor.startswith("bottom"):
            self.cfg["margin_y"] = max(0, mb - y - h)
        else:
            self.cfg["margin_y"] = 0

        # Remember which monitor we're on so next launch returns here
        self.cfg["monitor_rect"] = list(active)

    # -- Apply config -------------------------------------------------------
    def apply_config(self):
        # Toggles that affect the window itself
        self.root.attributes("-topmost", bool(self.cfg["always_on_top"]))
        self.root.after(50, self._apply_click_through)
        # Re-render with new settings — this also handles anchoring +
        # positioning in one atomic UpdateLayeredWindow call.
        self._render_now()
        # If the calendar is open, re-render it too so style changes take
        # effect immediately.
        try:
            if self.calendar.is_open():
                self.calendar._render_and_position()
        except Exception:
            pass

    def _current_colors(self):
        """Return (digit_color, digit_alpha, sep_color, sep_alpha)."""
        cfg = self.cfg
        return (cfg["color"], cfg["color_alpha"],
                cfg["sep_color"], cfg["sep_color_alpha"])

    # -- Render -------------------------------------------------------------
    def _compute_anchored_xy(self, w, h):
        """Return (x, y) where a w x h window should sit given the current
        anchor + margins + target monitor. Same logic as
        _position_from_anchor but pure — no side effects on the window."""
        ml, mt, mr, mb = self._pick_target_monitor()
        mw = mr - ml
        mh = mb - mt
        anchor = self.cfg.get("anchor", "top-right")
        mx = int(self.cfg.get("margin_x", 30))
        my = int(self.cfg.get("margin_y", 30))

        if anchor.endswith("left"):
            x = ml + mx
        elif anchor.endswith("right"):
            x = mr - w - mx
        else:
            x = ml + (mw - w) // 2

        if anchor.startswith("top"):
            y = mt + my
        elif anchor.startswith("bottom"):
            y = mb - h - my
        else:
            y = mt + (mh - h) // 2
        return x, y

    def _render_now(self):
        cfg = self.cfg
        eased, target_on = self.blink.update(
            int(cfg["blink_interval_ms"]),
            int(cfg["blink_anim_ms"]),
        )
        digit_on, digit_alpha, sep_on, sep_alpha = self._current_colors()
        off_color = cfg["blink_color_off"]

        # Separator color animation between sep_on and off_color
        if target_on:
            sep_from, sep_to = off_color, sep_on
        else:
            sep_from, sep_to = sep_on, off_color
        sep_color = lerp_color(sep_from, sep_to, eased)

        if cfg["blink_applies_to_digits"]:
            if target_on:
                digit_from, digit_to = off_color, digit_on
            else:
                digit_from, digit_to = digit_on, off_color
            digit_color = lerp_color(digit_from, digit_to, eased)
        else:
            digit_color = digit_on

        img = self.renderer.render(digit_color, sep_color,
                                   digit_alpha=digit_alpha,
                                   sep_alpha=sep_alpha)

        # If the calendar popup wants the clock hidden, blank the alpha
        # channel — the window stays where it is so hover detection and
        # geometry stay coherent, but nothing is drawn.
        if self._hidden:
            r, g, b, a = img.split()
            zero = a.point(lambda _: 0)
            img = Image.merge("RGBA", (r, g, b, zero))

        size_changed = (
            img.width != self._last_render_size[0]
            or img.height != self._last_render_size[1]
        )
        self._last_render_size = (img.width, img.height)

        # Compute where this frame should be drawn. If the user is dragging,
        # honor their hand position; otherwise the anchor is authoritative.
        # Anchoring BEFORE painting is critical: UpdateLayeredWindow both
        # paints AND repositions the window in one atomic call, so the
        # user never sees a frame at the wrong spot — and the painted
        # surface always matches Tk's idea of where the window is.
        if self._dragging:
            # Use what Tk currently thinks — that's what the drag handler
            # is updating via geometry().
            try:
                self.root.update_idletasks()
                target_x = self.root.winfo_x()
                target_y = self.root.winfo_y()
            except Exception:
                target_x, target_y = self._compute_anchored_xy(
                    img.width, img.height)
        else:
            target_x, target_y = self._compute_anchored_xy(
                img.width, img.height)

        # Update Tk's geometry so its hit-test rectangle matches the new
        # size and position (mouse events still flow through Tk).
        if size_changed or not self._dragging:
            self.root.geometry(f"{img.width}x{img.height}+{target_x}+{target_y}")

        # Push pixels to the OS-composited layered surface AT THE COMPUTED
        # POSITION (not winfo_x/y which may lag the geometry call).
        if self._layered_ready:
            hwnd = self._get_hwnd()
            if hwnd:
                try:
                    paint_layered_window(hwnd, img, target_x, target_y)
                except Exception:
                    # Fail silently — next tick will retry
                    pass

        # On first-launch when monitor_rect wasn't saved, _pick_target_monitor
        # records the monitor we used. Trigger that here too so a fresh
        # install gets its monitor pinned on the very first paint.
        if self.cfg.get("monitor_rect") is None and not self._dragging:
            mons = self._enum_monitors()
            for m in mons:
                if m[0] <= target_x < m[2] and m[1] <= target_y < m[3]:
                    self.cfg["monitor_rect"] = list(m)
                    save_config(self.cfg)
                    break

        return size_changed

    def _tick(self):
        self._render_now()
        # 50 ms = 20 fps animation. Smooth enough for blink, cheap on CPU.
        self.root.after(50, self._tick)


# ---------------------------------------------------------------------------
# Settings dialog — scrollable, grouped into tabs
# ---------------------------------------------------------------------------
class SettingsDialog:
    def __init__(self, clock):
        self.clock = clock
        self.cfg = clock.cfg
        self.win = tk.Toplevel(clock.root)
        self.win.title(f"{APP_NAME} Settings")
        self.win.attributes("-topmost", True)
        self.win.geometry("520x640")
        self.win.minsize(480, 480)
        self._build()

    # convenience constructors ---------------------------------------------
    def _section(self, parent, title):
        frame = ttk.LabelFrame(parent, text=title, padding=(8, 4))
        frame.pack(fill="x", padx=10, pady=6)
        return frame

    def _row(self, parent, label, width=22):
        frm = tk.Frame(parent)
        frm.pack(fill="x", pady=3)
        if label:
            tk.Label(frm, text=label, width=width, anchor="w").pack(side="left")
        return frm

    def _scale(self, parent, label, key, from_, to, resolution=1, width=22):
        frm = self._row(parent, label, width=width)
        if isinstance(resolution, float) or resolution < 1:
            var = tk.DoubleVar(value=float(self.cfg[key]))
        else:
            var = tk.IntVar(value=int(self.cfg[key]))
        scale = tk.Scale(
            frm, from_=from_, to=to, resolution=resolution,
            orient="horizontal", variable=var,
            command=lambda v: self._apply(
                key,
                float(v) if (isinstance(resolution, float) or resolution < 1) else int(float(v))),
        )
        scale.pack(side="left", fill="x", expand=True)
        return var

    def _check(self, parent, label, key, width=22):
        frm = self._row(parent, "", width=width)
        var = tk.BooleanVar(value=bool(self.cfg[key]))
        cb = tk.Checkbutton(frm, text=label, variable=var, anchor="w",
                            command=lambda: self._apply(key, var.get()))
        cb.pack(side="left", fill="x", expand=True)
        return var

    def _color(self, parent, label, key, width=22):
        frm = self._row(parent, label, width=width)
        swatch = tk.Label(frm, text=self.cfg[key], width=10,
                          bg=self.cfg[key], relief="solid", borderwidth=1)
        swatch.pack(side="left", padx=4)
        def pick():
            result = colorchooser.askcolor(color=self.cfg[key], parent=self.win)
            if result and result[1]:
                self._apply(key, result[1])
                swatch.config(bg=result[1], text=result[1])
        tk.Button(frm, text="Pick", command=pick).pack(side="left")
        return swatch

    def _option(self, parent, label, key, options, width=22):
        frm = self._row(parent, label, width=width)
        var = tk.StringVar(value=self.cfg[key])
        opt = tk.OptionMenu(frm, var, *options,
                            command=lambda *_: self._apply(key, var.get()))
        opt.pack(side="left", fill="x", expand=True)
        return var

    # build UI -------------------------------------------------------------
    def _build(self):
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- Build each tab in a scrollable frame -----------------------
        tabs = {}
        for name in ("Font", "Colors", "Effects", "Separator", "Date",
                     "Calendar", "Box", "Position", "Behavior"):
            outer = tk.Frame(nb)
            nb.add(outer, text=name)
            canvas = tk.Canvas(outer, highlightthickness=0)
            scroll = ttk.Scrollbar(outer, orient="vertical",
                                   command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            canvas.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            inner = tk.Frame(canvas)
            inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

            def _on_configure(event, c=canvas, w=inner_id):
                c.configure(scrollregion=c.bbox("all"))
                c.itemconfig(w, width=event.width)

            inner.bind("<Configure>",
                       lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
            canvas.bind("<Configure>", _on_configure)
            tabs[name] = inner

        # ===== Font tab =====
        f = self._section(tabs["Font"], "Font")
        # Font family — searchable-ish; OptionMenu lists too many, use a combo
        frm = self._row(f, "Font family")
        var_font = tk.StringVar(value=self.cfg["font_family"])
        cb = ttk.Combobox(frm, textvariable=var_font, state="readonly",
                          values=sorted(set(tkfont.families())))
        cb.pack(side="left", fill="x", expand=True)

        # Resolution status label updated whenever the font changes
        status_frm = self._row(f, "Loaded from")
        self._font_status_lbl = tk.Label(status_frm, text="", anchor="w",
                                         wraplength=320, justify="left",
                                         fg="#444")
        self._font_status_lbl.pack(side="left", fill="x", expand=True)

        def _on_font_pick(e=None):
            self._apply("font_family", var_font.get())
            self._refresh_font_status()

        cb.bind("<<ComboboxSelected>>", _on_font_pick)

        self._option(f, "Font weight", "font_weight", ["normal", "bold"])
        self._scale(f, "Font size (px)", "font_size", 20, 400, 1)
        # Initial status
        self._refresh_font_status()

        f = self._section(tabs["Font"], "Time format")
        self._check(f, "Use 24-hour", "hour_format_24")
        self._check(f, "Show AM/PM (12-hour only)", "show_ampm")
        self._check(f, "Show leading zero", "leading_zero")
        self._check(f, "Show seconds", "show_seconds")

        # ===== Colors tab =====
        f = self._section(tabs["Colors"], "Digit color")
        self._color(f, "Digit color", "color")
        self._scale(f, "Digit opacity", "color_alpha", 0.05, 1.0, 0.05)

        f = self._section(tabs["Colors"], "Separator color")
        self._color(f, "Separator color", "sep_color")
        self._scale(f, "Separator opacity", "sep_color_alpha", 0.05, 1.0, 0.05)

        # ===== Effects tab =====
        f = self._section(tabs["Effects"], "Text outline")
        self._check(f, "Enable outline", "text_outline_enabled")
        self._color(f, "Outline color", "text_outline_color")
        self._scale(f, "Outline thickness (px)", "text_outline_thickness", 0, 20, 1)

        f = self._section(tabs["Effects"], "Text shadow")
        self._check(f, "Enable text shadow", "text_shadow_enabled")
        self._color(f, "Shadow color", "text_shadow_color")
        self._scale(f, "Shadow offset X", "text_shadow_offset_x", -30, 30, 1)
        self._scale(f, "Shadow offset Y", "text_shadow_offset_y", -30, 30, 1)
        self._scale(f, "Shadow blur (px)", "text_shadow_blur", 0, 40, 1)
        self._scale(f, "Shadow opacity", "text_shadow_alpha", 0.0, 1.0, 0.05)

        # ===== Separator tab =====
        f = self._section(tabs["Separator"], "Separator style")
        self._option(f, "Style", "separator_style", SEPARATOR_STYLES)
        self._check(f, "Perfect circles (vs squares)", "separator_circle")
        self._scale(f, "Dot radius (% of font)", "separator_dot_radius_pct", 2, 30, 1)
        self._scale(f, "Vertical offset (% font)", "separator_y_offset_pct", -50, 50, 1)

        f = self._section(tabs["Separator"], "Spacing")
        self._scale(f, "Between digits (px)", "digit_spacing", -20, 80, 1)
        self._scale(f, "Around separator (px)", "separator_spacing", -20, 80, 1)

        f = self._section(tabs["Separator"], "Blink animation")
        self._scale(f, "Interval (ms, 0=off)", "blink_interval_ms", 0, 2000, 50)
        self._scale(f, "Transition duration (ms)", "blink_anim_ms", 0, 1000, 10)
        self._color(f, "Off color", "blink_color_off")
        self._check(f, "Blink applies to whole clock (not just separator)",
                    "blink_applies_to_digits")

        # ===== Date tab =====
        f = self._section(tabs["Date"], "Date")
        self._check(f, "Show date below time", "date_enabled")

        # Format presets — a combobox that's also free-text editable
        frm = self._row(f, "Format")
        var_dfmt = tk.StringVar(value=self.cfg["date_format"])
        date_presets = [
            "%A, %d %B %Y",        # Monday, 01 January 2026
            "%a, %d %b %Y",        # Mon, 01 Jan 2026
            "%d %B %Y",            # 01 January 2026
            "%d %b %Y",            # 01 Jan 2026
            "%d/%m/%Y",            # 01/06/2026
            "%m/%d/%Y",            # 06/01/2026
            "%Y-%m-%d",            # 2026-06-01
            "%A",                  # Monday
            "%d %B",               # 01 January
        ]
        cb_d = ttk.Combobox(frm, textvariable=var_dfmt, values=date_presets)
        cb_d.pack(side="left", fill="x", expand=True)

        def _apply_date_fmt(*_):
            self._apply("date_format", var_dfmt.get())

        cb_d.bind("<<ComboboxSelected>>", _apply_date_fmt)
        cb_d.bind("<Return>", _apply_date_fmt)
        cb_d.bind("<FocusOut>", _apply_date_fmt)

        # Live preview of what the format renders right now
        preview_frm = self._row(f, "Preview")
        self._date_preview_lbl = tk.Label(preview_frm, anchor="w",
                                          fg="#555")
        self._date_preview_lbl.pack(side="left", fill="x", expand=True)
        self._refresh_date_preview()
        # Re-render the preview as the user types into the combobox entry
        cb_d.bind("<KeyRelease>",
                  lambda e: self._refresh_date_preview(var_dfmt.get()))

        f = self._section(tabs["Date"], "Font")
        frm = self._row(f, "Font family")
        var_dfont = tk.StringVar(value=self.cfg["date_font_family"] or "")
        date_families = [""] + sorted(set(tkfont.families()))
        cb_df = ttk.Combobox(frm, textvariable=var_dfont, state="readonly",
                             values=date_families)
        cb_df.pack(side="left", fill="x", expand=True)
        cb_df.bind("<<ComboboxSelected>>",
                   lambda e: self._apply("date_font_family",
                                         var_dfont.get()))
        tk.Label(f, text="(leave blank to inherit the time's font)",
                 fg="#888").pack(anchor="w", padx=12)

        self._option(f, "Font weight", "date_font_weight", ["normal", "bold"])
        self._scale(f, "Font size (px)", "date_font_size", 8, 200, 1)
        self._check(f, "Stretch date to match time width",
                    "date_stretch_to_time")
        tk.Label(f, text="When stretched, font size is auto-computed and the "
                         "slider above is ignored.", fg="#888",
                 wraplength=440, justify="left").pack(anchor="w", padx=12)

        f = self._section(tabs["Date"], "Color")
        self._color(f, "Date color", "date_color")
        self._scale(f, "Date opacity", "date_color_alpha", 0.05, 1.0, 0.05)

        f = self._section(tabs["Date"], "Position")
        self._option(f, "Position", "date_position", ["below", "above"])
        self._scale(f, "Gap from time (px)", "date_gap", -200, 200, 1)
        self._option(f, "Alignment", "date_align",
                     ["left", "center", "right"])
        self._scale(f, "Horizontal offset (px)", "date_offset_x", -300, 300, 1)
        self._scale(f, "Letter spacing (px)", "date_letter_spacing", -5, 30, 1)

        # ===== Calendar tab =====
        f = self._section(tabs["Calendar"], "Behavior")
        self._check(f, "Enable calendar popup on hover", "calendar_enabled")
        self._scale(f, "Hover delay (ms)",
                    "calendar_hover_delay_ms", 300, 6000, 100)
        self._scale(f, "Dismiss delay after cursor leaves (ms)",
                    "calendar_dismiss_delay_ms", 0, 5000, 100)
        self._check(f, "Hide time while calendar is open",
                    "calendar_hide_time")

        f = self._section(tabs["Calendar"], "Placement")
        self._option(f, "Expand toward", "calendar_expand",
                     CALENDAR_EXPAND_DIRECTIONS)
        self._scale(f, "Distance from clock (px)",
                    "calendar_offset", -60, 60, 1)

        f = self._section(tabs["Calendar"], "Font")
        frm = self._row(f, "Font family")
        var_cf = tk.StringVar(value=self.cfg["calendar_font_family"] or "")
        cal_families = [""] + sorted(set(tkfont.families()))
        cb_cf = ttk.Combobox(frm, textvariable=var_cf, state="readonly",
                             values=cal_families)
        cb_cf.pack(side="left", fill="x", expand=True)
        cb_cf.bind("<<ComboboxSelected>>",
                   lambda e: self._apply("calendar_font_family",
                                         var_cf.get()))
        tk.Label(f, text="(leave blank to inherit the clock font)",
                 fg="#888").pack(anchor="w", padx=12)
        self._option(f, "Font weight", "calendar_font_weight",
                     ["normal", "bold"])
        self._scale(f, "Font size (px)", "calendar_font_size", 8, 48, 1)

        f = self._section(tabs["Calendar"], "Layout")
        self._scale(f, "Cell padding X (px)", "calendar_cell_padding_x",
                    0, 30, 1)
        self._scale(f, "Cell padding Y (px)", "calendar_cell_padding_y",
                    0, 30, 1)
        self._scale(f, "Row spacing (px)", "calendar_row_spacing", 0, 20, 1)
        self._scale(f, "Column spacing (px)", "calendar_col_spacing",
                    0, 20, 1)
        self._scale(f, "Digit spacing within date (px)",
                    "calendar_digit_spacing", -4, 12, 1)
        self._check(f, "Show leading zeros (else center single digits)",
                    "calendar_leading_zero")

        f = self._section(tabs["Calendar"], "Week")
        self._option(f, "Week starts on", "calendar_week_starts_on",
                     ["monday", "sunday"])
        self._option(f, "Weekend days", "calendar_weekend_days",
                     ["none", "sat-sun", "sun-only", "fri-sat"])
        self._check(f, "Highlight weekend days",
                    "calendar_highlight_weekend")
        self._option(f, "Highlight mode", "calendar_weekend_highlight_mode",
                     ["background", "foreground"])
        self._color(f, "Weekend highlight color", "calendar_weekend_color")
        self._scale(f, "Weekend highlight opacity",
                    "calendar_weekend_color_alpha", 0.05, 1.0, 0.05)

        f = self._section(tabs["Calendar"], "Colors")
        self._color(f, "Date number color", "calendar_color")
        self._scale(f, "Date opacity", "calendar_color_alpha", 0.05, 1.0, 0.05)
        self._color(f, "Today highlight color", "calendar_today_color")
        self._scale(f, "Today opacity", "calendar_today_color_alpha",
                    0.05, 1.0, 0.05)
        self._color(f, "Other-month color", "calendar_other_month_color")
        self._scale(f, "Other-month opacity",
                    "calendar_other_month_color_alpha", 0.05, 1.0, 0.05)
        self._color(f, "Header / weekday color", "calendar_header_color")
        self._scale(f, "Header opacity", "calendar_header_color_alpha",
                    0.05, 1.0, 0.05)

        f = self._section(tabs["Calendar"], "Background & box")
        self._color(f, "Background color", "calendar_bg_color")
        self._scale(f, "Background opacity", "calendar_bg_alpha",
                    0.0, 1.0, 0.05)
        self._check(f, "Rounded corners", "calendar_box_rounded")
        self._scale(f, "Corner radius (px)", "calendar_box_corner_radius",
                    0, 40, 1)
        self._check(f, "Show outline", "calendar_box_outline_enabled")
        self._color(f, "Outline color", "calendar_box_outline_color")
        self._scale(f, "Outline thickness (px)",
                    "calendar_box_outline_thickness", 1, 6, 1)

        # ===== Box tab =====
        f = self._section(tabs["Box"], "Background panel")
        self._check(f, "Enable background box", "box_enabled")
        self._color(f, "Box color", "box_color")
        self._scale(f, "Box opacity", "bg_alpha", 0.0, 1.0, 0.05)
        self._scale(f, "Corner radius (px)", "box_corner_radius", 0, 100, 1)

        f = self._section(tabs["Box"], "Padding (negative tightens the box)")
        self._scale(f, "Inner padding X", "box_padding_inner_x", -80, 100, 1)
        self._scale(f, "Inner padding Y", "box_padding_inner_y", -80, 100, 1)
        self._scale(f, "Outer padding X", "box_padding_outer_x", 0, 200, 1)
        self._scale(f, "Outer padding Y", "box_padding_outer_y", 0, 200, 1)

        f = self._section(tabs["Box"], "Box outline")
        self._check(f, "Enable box outline", "box_outline_enabled")
        self._color(f, "Outline color", "box_outline_color")
        self._scale(f, "Outline thickness (px)", "box_outline_thickness", 0, 20, 1)

        f = self._section(tabs["Box"], "Box shadow")
        self._check(f, "Enable box shadow", "box_shadow_enabled")
        self._color(f, "Shadow color", "box_shadow_color")
        self._scale(f, "Shadow offset X", "box_shadow_offset_x", -40, 40, 1)
        self._scale(f, "Shadow offset Y", "box_shadow_offset_y", -40, 40, 1)
        self._scale(f, "Shadow blur (px)", "box_shadow_blur", 0, 60, 1)
        self._scale(f, "Shadow opacity", "box_shadow_alpha", 0.0, 1.0, 0.05)

        # ===== Position tab =====
        f = self._section(tabs["Position"], "Anchor")
        self._option(f, "Anchor", "anchor", ANCHORS)
        self._scale(f, "Margin X (px from edge)", "margin_x", 0, 800, 1)
        self._scale(f, "Margin Y (px from edge)", "margin_y", 0, 800, 1)

        f = self._section(tabs["Position"], "Monitor")
        # Show the saved/active monitor and let the user re-identify them.
        self._monitor_status_lbl = tk.Label(f, text="", anchor="w",
                                            wraplength=440, justify="left",
                                            fg="#444")
        self._monitor_status_lbl.pack(anchor="w", padx=12, pady=(0, 4))

        btn_row = tk.Frame(f)
        btn_row.pack(anchor="w", padx=12, pady=(0, 6))
        tk.Button(btn_row, text="Identify monitors",
                  command=lambda: self.clock.identify_monitors()
                  ).pack(side="left")
        tk.Button(btn_row, text="Move to current monitor",
                  command=self._move_to_current_monitor
                  ).pack(side="left", padx=8)
        self._refresh_monitor_status()

        # ===== Behavior tab =====
        f = self._section(tabs["Behavior"], "Window")
        self._check(f, "Always on top", "always_on_top")

        # Click-through and Draggable are coupled: when click-through is on,
        # the OS routes all mouse events through the window so dragging
        # cannot work. Keep the *stored* draggable preference intact, but
        # disable the checkbox visually so the user understands.
        frm_ct = self._row(f, "", width=22)
        var_ct = tk.BooleanVar(value=bool(self.cfg["click_through"]))
        frm_drag = self._row(f, "", width=22)
        var_drag = tk.BooleanVar(value=bool(self.cfg["draggable"]))
        drag_cb = tk.Checkbutton(frm_drag, text="Draggable",
                                 variable=var_drag, anchor="w",
                                 command=lambda: self._apply(
                                     "draggable", var_drag.get()))
        drag_cb.pack(side="left", fill="x", expand=True)

        def _sync_draggable_state():
            if var_ct.get():
                drag_cb.configure(state="disabled")
            else:
                drag_cb.configure(state="normal")

        def _on_click_through_change():
            self._apply("click_through", var_ct.get())
            _sync_draggable_state()

        ct_cb = tk.Checkbutton(frm_ct,
                               text="Click-through (mouse passes through)",
                               variable=var_ct, anchor="w",
                               command=_on_click_through_change)
        ct_cb.pack(side="left", fill="x", expand=True)
        _sync_draggable_state()

        f = self._section(tabs["Behavior"], "Startup")
        frm = self._row(f, "")
        var_auto = tk.BooleanVar(value=is_autostart_enabled())
        def _toggle():
            ok = set_autostart(var_auto.get())
            if not ok:
                messagebox.showerror(APP_NAME,
                                     "Could not modify Windows startup entry.",
                                     parent=self.win)
                var_auto.set(is_autostart_enabled())
        tk.Checkbutton(frm, text="Start with Windows",
                       variable=var_auto, command=_toggle).pack(side="left")

        # Close button at the bottom (outside the notebook)
        bar = tk.Frame(self.win)
        bar.pack(fill="x", pady=(0, 8))
        tk.Button(bar, text="Close", command=self.win.destroy,
                  width=14).pack(side="right", padx=12)
        tk.Button(bar, text="Reset to defaults",
                  command=self._reset_defaults).pack(side="left", padx=12)

    def _apply(self, key, value):
        self.cfg[key] = value
        save_config(self.cfg)
        self.clock.apply_config()
        if key in ("font_family", "font_weight"):
            self._refresh_font_status()
        if key in ("anchor", "margin_x", "margin_y"):
            self._refresh_monitor_status()
        if key == "date_format":
            self._refresh_date_preview()

    def _refresh_font_status(self):
        """Show what file was actually loaded for the selected font."""
        if not hasattr(self, "_font_status_lbl"):
            return
        fam = self.cfg.get("font_family", "")
        weight = self.cfg.get("font_weight", "normal")
        info = _font_resolution_log.get((fam, weight))
        if info is None:
            # Force a lookup so the status is populated
            try:
                get_pillow_font(fam, int(self.cfg.get("font_size", 100)),
                                weight)
                info = _font_resolution_log.get((fam, weight))
            except Exception:
                info = None
        if info is None:
            txt = "(not yet loaded)"
            color = "#888"
        else:
            status, detail = info
            if status == "found":
                txt = f"✓ {Path(detail).name}"
                color = "#06700a"
            elif status.startswith("BITMAP"):
                txt = f"⚠ {status} — pick a different font"
                color = "#a00"
            elif status.startswith("error"):
                txt = f"⚠ {status}"
                color = "#a00"
            elif status == "fallback-dejavu":
                txt = "⚠ Fell back to DejaVuSans (font not found)"
                color = "#a00"
            else:
                txt = f"… {status}: {detail}"
                color = "#888"
        self._font_status_lbl.configure(text=txt, fg=color)

    def _refresh_date_preview(self, fmt=None):
        """Show what the current date format renders to right now."""
        if not hasattr(self, "_date_preview_lbl"):
            return
        if fmt is None:
            fmt = self.cfg.get("date_format", "")
        try:
            preview = datetime.now().strftime(fmt) if fmt else "(empty)"
            self._date_preview_lbl.configure(text=preview, fg="#444")
        except Exception as e:
            self._date_preview_lbl.configure(
                text=f"Invalid format: {e}", fg="#a00")

    def _refresh_monitor_status(self):
        """Show which monitor the clock is anchored to."""
        if not hasattr(self, "_monitor_status_lbl"):
            return
        mons = self.clock._enum_monitors()
        active = self.clock._active_monitor_rect()
        target = self.clock._pick_target_monitor()

        def fmt(rect):
            l, t, r, b = rect
            return f"{r-l}x{b-t} at ({l}, {t})"

        # Find the index of the target monitor
        idx_target = next((i + 1 for i, m in enumerate(mons) if m == target),
                         "?")
        idx_active = next((i + 1 for i, m in enumerate(mons) if m == active),
                         "?")

        lines = []
        lines.append(f"Clock is anchored to monitor #{idx_target} "
                     f"({fmt(target)})")
        if active != target:
            lines.append(f"(physically currently on monitor #{idx_active})")
        lines.append("")
        lines.append("All connected monitors:")
        for i, m in enumerate(mons, start=1):
            mark = " ←" if m == target else ""
            lines.append(f"  #{i}: {fmt(m)}{mark}")
        self._monitor_status_lbl.configure(text="\n".join(lines))

    def _move_to_current_monitor(self):
        """Re-anchor the clock to whichever monitor it's physically on now.
        Useful if you've fiddled with anchor/margins and the clock ends up
        somewhere weird, or if you want to reset which monitor is 'home'."""
        active = self.clock._active_monitor_rect()
        self.clock.cfg["monitor_rect"] = list(active)
        save_config(self.clock.cfg)
        self.clock.apply_config()
        self._refresh_monitor_status()

    def _reset_defaults(self):
        if not messagebox.askyesno(APP_NAME,
                                   "Reset all settings to defaults?",
                                   parent=self.win):
            return
        for k, v in DEFAULT_CONFIG.items():
            self.cfg[k] = v
        save_config(self.cfg)
        self.clock.apply_config()
        # Rebuild dialog so widgets reflect new values
        self.win.destroy()
        SettingsDialog(self.clock)


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------
def make_tray_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), outline=(255, 255, 255, 255), width=3)
    d.line((32, 32, 32, 12), fill=(255, 255, 255, 255), width=3)
    d.line((32, 32, 48, 36), fill=(255, 255, 255, 255), width=3)
    return img


# ===========================================================================
# Calendar popup
# ===========================================================================

WEEKEND_PRESETS = {
    "none":     set(),
    "sun-only": {6},               # ISO weekday: Mon=0..Sun=6
    "sat-sun":  {5, 6},
    "fri-sat":  {4, 5},
}


def _weekday_iso(date_obj):
    """Return 0=Mon ... 6=Sun for a datetime.date."""
    return date_obj.weekday()


class CalendarPopup:
    """A month-view calendar that appears next to the clock on hover.

    The popup is a layered Tk Toplevel: its visible pixels come from a
    Pillow-rendered image painted via UpdateLayeredWindow (so we get
    per-pixel alpha for rounded corners), but it still receives mouse
    clicks on opaque pixels. We bake the calendar into one bitmap and
    keep an in-memory hit-test table to dispatch clicks.
    """

    def __init__(self, clock):
        self.clock = clock
        self.cfg = clock.cfg
        self.top = None
        self._image_size = (0, 0)
        self._hit_targets = []        # list of (x1, y1, x2, y2, callback)
        self._hover_inside = False    # mouse is over the calendar itself
        # Calendar state — what month is being shown
        today = datetime.now().date()
        self.view_year = today.year
        self.view_month = today.month
        self._editing_year = False
        self._year_buffer = str(self.view_year)

    # ----- Lifecycle ------------------------------------------------------
    def is_open(self):
        return self.top is not None and self.top.winfo_exists()

    def open(self):
        if self.is_open():
            return
        # Reset to today's month each time we open
        today = datetime.now().date()
        self.view_year = today.year
        self.view_month = today.month
        self._editing_year = False
        self._year_buffer = str(self.view_year)

        self.top = tk.Toplevel(self.clock.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        # Layered window for crisp rounded corners against any backdrop
        self.top.update_idletasks()
        try:
            hwnd = self._hwnd()
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            # NOT setting WS_EX_TRANSPARENT — we want clicks on opaque pixels
            style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

        # Dummy canvas so the toplevel has a sized content area for events
        self._dummy = tk.Canvas(self.top, width=1, height=1,
                                highlightthickness=0, bd=0)
        self._dummy.pack()

        # Bind mouse handlers on both the toplevel and the dummy canvas
        for w in (self.top, self._dummy):
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            # Mouse wheel scrolls months in the year picker if active,
            # otherwise scrolls months.
            w.bind("<MouseWheel>", self._on_wheel)

        # Hide the clock if configured
        if self.cfg.get("calendar_hide_time", False):
            self.clock.set_hidden(True)

        self._render_and_position()

    def close(self):
        if not self.is_open():
            return
        try:
            self.top.destroy()
        except Exception:
            pass
        self.top = None
        # Always restore the clock
        try:
            self.clock.set_hidden(False)
        except Exception:
            pass

    def _hwnd(self):
        try:
            child = self.top.winfo_id()
            parent = ctypes.windll.user32.GetParent(child)
            return parent if parent else child
        except Exception:
            return 0

    # ----- Navigation -----------------------------------------------------
    def _prev_month(self):
        if self.view_month == 1:
            self.view_month = 12
            self.view_year -= 1
        else:
            self.view_month -= 1
        self._editing_year = False
        self._render_and_position()

    def _next_month(self):
        if self.view_month == 12:
            self.view_month = 1
            self.view_year += 1
        else:
            self.view_month += 1
        self._editing_year = False
        self._render_and_position()

    def _year_dec(self):
        self.view_year -= 1
        self._year_buffer = str(self.view_year)
        self._render_and_position()

    def _year_inc(self):
        self.view_year += 1
        self._year_buffer = str(self.view_year)
        self._render_and_position()

    def _toggle_year_editor(self):
        self._editing_year = not self._editing_year
        self._year_buffer = str(self.view_year)
        self._render_and_position()

    # ----- Event handlers -------------------------------------------------
    def _on_enter(self, e):
        self._hover_inside = True

    def _on_leave(self, e):
        # Tk fires Leave when the cursor enters a child widget too. Use a
        # short delayed check against the real cursor position.
        self._hover_inside = False

    def _on_click(self, e):
        # Use widget-local coordinates so it works whether the event came
        # from the toplevel or the dummy canvas.
        x = e.x_root - self.top.winfo_rootx()
        y = e.y_root - self.top.winfo_rooty()
        for (x1, y1, x2, y2, cb) in self._hit_targets:
            if x1 <= x < x2 and y1 <= y < y2:
                cb()
                return

    def _on_wheel(self, e):
        delta = 1 if e.delta > 0 else -1
        if self._editing_year:
            self.view_year += delta
            self._year_buffer = str(self.view_year)
        else:
            if delta > 0:
                self._prev_month()
                return
            else:
                self._next_month()
                return
        self._render_and_position()

    # ----- Rendering ------------------------------------------------------
    def _font(self, size=None, weight=None):
        cfg = self.cfg
        family = cfg.get("calendar_font_family") or cfg.get("font_family")
        if size is None:
            size = int(cfg.get("calendar_font_size", 18))
        if weight is None:
            weight = cfg.get("calendar_font_weight", "normal")
        return get_pillow_font(family, size, weight)

    def _rgba(self, hex_color, alpha):
        r, g, b = hex_to_rgb(hex_color)
        a = int(max(0.0, min(1.0, float(alpha))) * 255)
        return (r, g, b, a)

    def _weekday_labels(self):
        cfg = self.cfg
        starts_on = cfg.get("calendar_week_starts_on", "monday")
        # Mon..Sun
        base = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        if starts_on == "sunday":
            return base[-1:] + base[:-1], 6  # offset
        return base, 0

    def _weekend_set(self):
        return WEEKEND_PRESETS.get(
            self.cfg.get("calendar_weekend_days", "sat-sun"),
            {5, 6})

    def _month_grid(self):
        """Return a list of 6 rows × 7 cells of date objects, including
        the leading days of the prior month and trailing days of the
        following month to fill the grid."""
        from calendar import monthrange
        from datetime import date as _date, timedelta

        first = _date(self.view_year, self.view_month, 1)
        days_in_month = monthrange(self.view_year, self.view_month)[1]
        first_weekday_iso = first.weekday()    # Mon=0 .. Sun=6
        starts_on = self.cfg.get("calendar_week_starts_on", "monday")
        if starts_on == "sunday":
            # Shift so Sun column index is 0
            offset = (first_weekday_iso + 1) % 7
        else:
            offset = first_weekday_iso

        grid_start = first - timedelta(days=offset)
        cells = []
        for i in range(42):
            cells.append(grid_start + timedelta(days=i))
        return cells

    def _render_and_position(self):
        if not self.is_open():
            return
        img, hit_targets = self._build_image()
        self._hit_targets = hit_targets
        self._image_size = (img.width, img.height)

        x, y = self._compute_position(img.width, img.height)

        # Update the Tk window's geometry so its hit area matches the image
        self.top.geometry(f"{img.width}x{img.height}+{x}+{y}")
        try:
            paint_layered_window(self._hwnd(), img, x, y)
        except Exception:
            pass

    def _build_image(self):
        """Render the calendar to a Pillow RGBA image. Returns (img, hits)
        where hits is the list of clickable rect tuples."""
        cfg = self.cfg
        from datetime import date as _date

        today = datetime.now().date()
        weekday_labels, _ = self._weekday_labels()
        weekend_set = self._weekend_set()
        cells = self._month_grid()

        # Fonts
        body_font = self._font()
        body_ascent, body_descent = body_font.getmetrics()
        body_line_h = body_ascent + body_descent
        header_font = self._font(size=int(cfg["calendar_font_size"] * 1.2),
                                 weight="bold")
        header_ascent, header_descent = header_font.getmetrics()
        header_line_h = header_ascent + header_descent

        # Cell sizing — the widest 2-digit numeral defines the column width
        cell_pad_x = int(cfg.get("calendar_cell_padding_x", 6))
        cell_pad_y = int(cfg.get("calendar_cell_padding_y", 4))
        row_spacing = int(cfg.get("calendar_row_spacing", 2))
        col_spacing = int(cfg.get("calendar_col_spacing", 2))
        digit_spacing = int(cfg.get("calendar_digit_spacing", 0))
        leading_zero = bool(cfg.get("calendar_leading_zero", False))

        # Measure widest digit
        max_digit_w = 0
        max_digit_h = 0
        for d in "0123456789":
            bbox = body_font.getbbox(d)
            max_digit_w = max(max_digit_w, bbox[2] - bbox[0])
            max_digit_h = max(max_digit_h, bbox[3] - bbox[1])
        # Each cell needs to hold up to 2 digits + optional digit_spacing
        max_text_w = (2 * max_digit_w) + digit_spacing
        # Also weekday header may be wider than 2 digits
        for lbl in weekday_labels:
            bbox = body_font.getbbox(lbl)
            max_text_w = max(max_text_w, bbox[2] - bbox[0])

        col_w = max_text_w + 2 * cell_pad_x
        row_h = body_line_h + 2 * cell_pad_y

        # Layout: header row, weekday row, 6 date rows
        total_cols = 7
        grid_w = total_cols * col_w + (total_cols - 1) * col_spacing
        weekday_row_y = 0  # set after header is rendered
        # Header includes month-year navigation
        # We'll lay out: [< button] [Month Year (clickable) / year-editor] [> button]
        header_h = max(header_line_h + 12, row_h)

        outer_pad_x = 14
        outer_pad_y = 12
        gap_after_header = 6
        gap_after_weekdays = 4

        canvas_w = grid_w + 2 * outer_pad_x
        canvas_h = (outer_pad_y + header_h + gap_after_header
                    + row_h + gap_after_weekdays
                    + 6 * row_h + 5 * row_spacing
                    + outer_pad_y)

        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # Background rectangle (rounded or square)
        bg_fill = self._rgba(cfg["calendar_bg_color"],
                             cfg["calendar_bg_alpha"])
        if cfg.get("calendar_box_rounded", True):
            radius = max(0, int(cfg.get("calendar_box_corner_radius", 14)))
            try:
                d.rounded_rectangle((0, 0, canvas_w - 1, canvas_h - 1),
                                    radius=radius, fill=bg_fill)
            except AttributeError:
                d.rectangle((0, 0, canvas_w - 1, canvas_h - 1), fill=bg_fill)
        else:
            d.rectangle((0, 0, canvas_w - 1, canvas_h - 1), fill=bg_fill)

        # Outline
        if cfg.get("calendar_box_outline_enabled", False):
            outline_fill = self._rgba(cfg["calendar_box_outline_color"], 1.0)
            thickness = max(1, int(cfg["calendar_box_outline_thickness"]))
            if cfg.get("calendar_box_rounded", True):
                radius = max(0, int(cfg.get("calendar_box_corner_radius", 14)))
                try:
                    d.rounded_rectangle((0, 0, canvas_w - 1, canvas_h - 1),
                                        radius=radius, outline=outline_fill,
                                        width=thickness)
                except AttributeError:
                    d.rectangle((0, 0, canvas_w - 1, canvas_h - 1),
                                outline=outline_fill, width=thickness)
            else:
                d.rectangle((0, 0, canvas_w - 1, canvas_h - 1),
                            outline=outline_fill, width=thickness)

        hit_targets = []

        # ---- Header row: < Month Year > ----
        header_y = outer_pad_y
        header_color = self._rgba(cfg["calendar_header_color"],
                                  cfg["calendar_header_color_alpha"])
        nav_btn_w = max(28, header_line_h)

        # Prev button "<"
        prev_x1 = outer_pad_x
        prev_y1 = header_y + (header_h - nav_btn_w) // 2
        prev_x2 = prev_x1 + nav_btn_w
        prev_y2 = prev_y1 + nav_btn_w
        d.text(((prev_x1 + prev_x2) // 2, (prev_y1 + prev_y2) // 2),
               "‹", font=header_font, fill=header_color, anchor="mm")
        hit_targets.append((prev_x1 - 4, prev_y1 - 4, prev_x2 + 4,
                            prev_y2 + 4, self._prev_month))

        # Next button ">"
        next_x2 = canvas_w - outer_pad_x
        next_x1 = next_x2 - nav_btn_w
        next_y1 = prev_y1
        next_y2 = prev_y2
        d.text(((next_x1 + next_x2) // 2, (next_y1 + next_y2) // 2),
               "›", font=header_font, fill=header_color, anchor="mm")
        hit_targets.append((next_x1 - 4, next_y1 - 4, next_x2 + 4,
                            next_y2 + 4, self._next_month))

        # Center: "January  2026" or year edit mode "January  [‹ 2026 ›]"
        month_name = _date(self.view_year, self.view_month, 1).strftime("%B")
        center_x = canvas_w // 2
        center_y = (prev_y1 + prev_y2) // 2
        if not self._editing_year:
            label = f"{month_name}  {self.view_year}"
            d.text((center_x, center_y), label, font=header_font,
                   fill=header_color, anchor="mm")
            # Whole center area is clickable to toggle year editor
            label_bb = header_font.getbbox(label)
            label_w = label_bb[2] - label_bb[0]
            label_h = label_bb[3] - label_bb[1]
            cx1 = center_x - label_w // 2 - 6
            cx2 = center_x + label_w // 2 + 6
            cy1 = center_y - label_h // 2 - 6
            cy2 = center_y + label_h // 2 + 6
            hit_targets.append((cx1, cy1, cx2, cy2,
                                self._toggle_year_editor))
        else:
            # In editor mode: month name on the left of center, [‹ year ›]
            # on the right.
            m_label = month_name + " "
            year_str = str(self.view_year)
            m_bb = header_font.getbbox(m_label)
            y_bb = header_font.getbbox(year_str)
            inner_btn_w = nav_btn_w * 0.7
            spacer = 6
            total_w = ((m_bb[2] - m_bb[0]) + (y_bb[2] - y_bb[0])
                       + 2 * inner_btn_w + 4 * spacer)
            start_x = center_x - total_w // 2
            # Month name
            d.text((start_x, center_y), m_label, font=header_font,
                   fill=header_color, anchor="lm")
            cur_x = start_x + (m_bb[2] - m_bb[0]) + spacer
            # Decrement arrow
            yb_x1 = cur_x
            yb_y1 = center_y - inner_btn_w // 2
            yb_x2 = cur_x + inner_btn_w
            yb_y2 = center_y + inner_btn_w // 2
            d.text(((yb_x1 + yb_x2) // 2, center_y),
                   "‹", font=header_font, fill=header_color, anchor="mm")
            hit_targets.append((yb_x1, yb_y1, yb_x2, yb_y2, self._year_dec))
            cur_x = yb_x2 + spacer
            # Year text (clicking it commits and exits editor)
            d.text((cur_x, center_y), year_str, font=header_font,
                   fill=header_color, anchor="lm")
            year_w = y_bb[2] - y_bb[0]
            hit_targets.append((cur_x - 4, center_y - 14,
                                cur_x + year_w + 4, center_y + 14,
                                self._toggle_year_editor))
            cur_x = cur_x + year_w + spacer
            # Increment arrow
            yb2_x1 = cur_x
            yb2_y1 = center_y - inner_btn_w // 2
            yb2_x2 = cur_x + inner_btn_w
            yb2_y2 = center_y + inner_btn_w // 2
            d.text(((yb2_x1 + yb2_x2) // 2, center_y),
                   "›", font=header_font, fill=header_color, anchor="mm")
            hit_targets.append((yb2_x1, yb2_y1, yb2_x2, yb2_y2,
                                self._year_inc))

        # ---- Weekday header row ----
        weekday_y = header_y + header_h + gap_after_header
        for col, lbl in enumerate(weekday_labels):
            cx = outer_pad_x + col * (col_w + col_spacing) + col_w // 2
            d.text((cx, weekday_y + row_h // 2), lbl,
                   font=body_font, fill=header_color, anchor="mm")

        # ---- Date cells ----
        first_row_y = weekday_y + row_h + gap_after_weekdays
        default_color = self._rgba(cfg["calendar_color"],
                                   cfg["calendar_color_alpha"])
        today_color = self._rgba(cfg["calendar_today_color"],
                                 cfg["calendar_today_color_alpha"])
        other_color = self._rgba(cfg["calendar_other_month_color"],
                                 cfg["calendar_other_month_color_alpha"])
        weekend_color_fg = self._rgba(cfg["calendar_weekend_color"],
                                       cfg["calendar_weekend_color_alpha"])
        weekend_color_bg = self._rgba(cfg["calendar_weekend_color"],
                                       cfg["calendar_weekend_color_alpha"])
        highlight_mode = cfg.get("calendar_weekend_highlight_mode",
                                 "background")
        highlight_weekend = cfg.get("calendar_highlight_weekend", True)

        for i, date_obj in enumerate(cells):
            row = i // 7
            col = i % 7
            cell_x = outer_pad_x + col * (col_w + col_spacing)
            cell_y = first_row_y + row * (row_h + row_spacing)

            is_this_month = (date_obj.month == self.view_month)
            is_today = (date_obj == today)
            iso_wd = _weekday_iso(date_obj)
            is_weekend = iso_wd in weekend_set

            # Background highlight for weekends
            if (highlight_weekend and is_weekend and is_this_month
                    and highlight_mode == "background"):
                try:
                    d.rounded_rectangle(
                        (cell_x, cell_y,
                         cell_x + col_w - 1, cell_y + row_h - 1),
                        radius=6, fill=weekend_color_bg)
                except AttributeError:
                    d.rectangle(
                        (cell_x, cell_y,
                         cell_x + col_w - 1, cell_y + row_h - 1),
                        fill=weekend_color_bg)

            # Today's highlight ring on top of weekend bg
            if is_today and is_this_month:
                try:
                    d.rounded_rectangle(
                        (cell_x, cell_y,
                         cell_x + col_w - 1, cell_y + row_h - 1),
                        radius=6, outline=today_color, width=2)
                except AttributeError:
                    d.rectangle(
                        (cell_x, cell_y,
                         cell_x + col_w - 1, cell_y + row_h - 1),
                        outline=today_color, width=2)

            # Pick text color
            if not is_this_month:
                fg = other_color
            elif (highlight_weekend and is_weekend
                  and highlight_mode == "foreground"):
                fg = weekend_color_fg
            elif is_today:
                fg = today_color
            else:
                fg = default_color

            # Render number with the leading-zero / digit-spacing options
            day = date_obj.day
            if leading_zero:
                num = f"{day:02d}"
                self._draw_number(d, num, body_font, fg,
                                  cell_x, cell_y, col_w, row_h,
                                  digit_spacing)
            else:
                num = str(day)
                # No leading zero: center-align the single/double digit
                self._draw_number(d, num, body_font, fg,
                                  cell_x, cell_y, col_w, row_h,
                                  digit_spacing)

            # Make each cell clickable — closes the popup
            hit_targets.append((cell_x, cell_y,
                                cell_x + col_w, cell_y + row_h,
                                self.close))

        return img, hit_targets

    def _draw_number(self, d, num, font, fg, cell_x, cell_y, col_w, row_h,
                     digit_spacing):
        """Draw a (possibly multi-digit) number centered inside a cell,
        honoring per-digit spacing."""
        # Measure total width
        widths = []
        for ch in num:
            bb = font.getbbox(ch)
            widths.append(bb[2] - bb[0])
        total_w = sum(widths) + max(0, len(num) - 1) * digit_spacing
        start_x = cell_x + (col_w - total_w) // 2
        cy = cell_y + row_h // 2
        cur_x = start_x
        for ch, w in zip(num, widths):
            d.text((cur_x, cy), ch, font=font, fill=fg, anchor="lm")
            cur_x += w + digit_spacing

    # ----- Positioning relative to the clock ------------------------------
    def _compute_position(self, w, h):
        """Place the calendar relative to the clock box per the
        calendar_expand setting. The setting names a direction the popup
        extends in: e.g. 'expand-down' = below the clock."""
        cfg = self.cfg
        offset = int(cfg.get("calendar_offset", 12))
        expand = cfg.get("calendar_expand", "expand-down")

        cx = self.clock.root.winfo_x()
        cy = self.clock.root.winfo_y()
        cw = self.clock.root.winfo_width()
        ch = self.clock.root.winfo_height()

        # Default: directly below
        x = cx + (cw - w) // 2
        y = cy + ch + offset

        if "left" in expand and "right" not in expand:
            x = cx - w - offset
            y = cy + (ch - h) // 2
        elif "right" in expand and "left" not in expand:
            x = cx + cw + offset
            y = cy + (ch - h) // 2
        elif "up" in expand and "down" not in expand:
            x = cx + (cw - w) // 2
            y = cy - h - offset
        elif "down" in expand:
            x = cx + (cw - w) // 2
            y = cy + ch + offset

        # Refinement for diagonal directions
        if "down-left" in expand:
            x = cx - w - offset
            y = cy + ch + offset
        elif "down-right" in expand:
            x = cx + cw + offset
            y = cy + ch + offset
        elif "up-left" in expand:
            x = cx - w - offset
            y = cy - h - offset
        elif "up-right" in expand:
            x = cx + cw + offset
            y = cy - h - offset

        # Clamp to the clock's current monitor's bounds so we don't go
        # off-screen
        try:
            mons = self.clock._enum_monitors()
            # Use the monitor the clock is on
            cx_mid = cx + cw // 2
            cy_mid = cy + ch // 2
            active = (0, 0, 1920, 1080)
            for m in mons:
                if m[0] <= cx_mid < m[2] and m[1] <= cy_mid < m[3]:
                    active = m
                    break
            ml, mt, mr, mb = active
            x = max(ml, min(mr - w, x))
            y = max(mt, min(mb - h, y))
        except Exception:
            pass

        return x, y


CALENDAR_EXPAND_DIRECTIONS = [
    "expand-up-left",   "expand-up",   "expand-up-right",
    "expand-left",                       "expand-right",
    "expand-down-left", "expand-down", "expand-down-right",
]


class TrayApp:
    def __init__(self, clock):
        self.clock = clock
        self.icon = None

    def _on_settings(self, icon, item):
        self.clock.root.after(0, self._open_settings)

    def _open_settings(self):
        for w in self.clock.root.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.lift()
                return
        SettingsDialog(self.clock)

    def _toggle(self, key):
        def handler(icon, item):
            self.clock.cfg[key] = not self.clock.cfg.get(key, False)
            save_config(self.clock.cfg)
            self.clock.root.after(0, self.clock.apply_config)
        return handler

    def _checked(self, key):
        return lambda item: bool(self.clock.cfg.get(key, False))

    def _set_anchor(self, anchor):
        def handler(icon, item):
            self.clock.cfg["anchor"] = anchor
            save_config(self.clock.cfg)
            self.clock.root.after(0, self.clock.apply_config)
        return handler

    def _anchor_checked(self, anchor):
        return lambda item: self.clock.cfg.get("anchor") == anchor

    def _quit(self, icon, item):
        icon.stop()
        self.clock.root.after(0, self.clock.root.destroy)

    def run(self):
        anchor_menu = pystray.Menu(*[
            pystray.MenuItem(a, self._set_anchor(a),
                             checked=self._anchor_checked(a), radio=True)
            for a in ANCHORS
        ])

        menu = pystray.Menu(
            pystray.MenuItem("Settings…", self._on_settings, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Anchor", anchor_menu),
            pystray.MenuItem("Always on top",
                             self._toggle("always_on_top"),
                             checked=self._checked("always_on_top")),
            pystray.MenuItem("Click-through",
                             self._toggle("click_through"),
                             checked=self._checked("click_through")),
            pystray.MenuItem("Draggable",
                             self._toggle("draggable"),
                             checked=self._checked("draggable"),
                             enabled=lambda item: not bool(
                                 self.clock.cfg.get("click_through", False))),
            pystray.MenuItem("24-hour",
                             self._toggle("hour_format_24"),
                             checked=self._checked("hour_format_24")),
            pystray.MenuItem("Leading zero",
                             self._toggle("leading_zero"),
                             checked=self._checked("leading_zero")),
            pystray.MenuItem("Show seconds",
                             self._toggle("show_seconds"),
                             checked=self._checked("show_seconds")),
            pystray.MenuItem("Show date",
                             self._toggle("date_enabled"),
                             checked=self._checked("date_enabled")),
            pystray.MenuItem("Calendar on hover",
                             self._toggle("calendar_enabled"),
                             checked=self._checked("calendar_enabled")),
            pystray.MenuItem("Background box",
                             self._toggle("box_enabled"),
                             checked=self._checked("box_enabled")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start with Windows",
                             lambda icon, item: set_autostart(
                                 not is_autostart_enabled()),
                             checked=lambda item: is_autostart_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon = pystray.Icon(APP_NAME, make_tray_image(), APP_NAME, menu)
        threading.Thread(target=self.icon.run, daemon=True).start()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    lock = SingleInstance()
    if lock.already_running:
        sys.exit(0)
    cfg = load_config()
    clock = ClockWindow(cfg)
    tray = TrayApp(clock)
    tray.run()
    try:
        clock.root.mainloop()
    finally:
        if tray.icon is not None:
            try:
                tray.icon.stop()
            except Exception:
                pass
        lock.release()


if __name__ == "__main__":
    main()

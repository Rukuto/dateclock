# DateClock — Deploy Guide

A large, customisable, antialiased digital clock for Windows 10/11, with
an optional date row and a hover-to-open month calendar.

This guide walks you through everything from raw source files to a real
installed Windows app. You do **not** need to be a developer.

---

## What you'll end up with

* A clock on screen at all times (toggle-able).
* A tray icon in the Windows taskbar — right-click for the full menu.
* A scrollable settings dialog with nine tabs (Font, Colors, Effects,
  Separator, Date, Calendar, Box, Position, Behavior).
* Optional date row inside the same box.
* Optional month calendar that appears when you hover the clock.
* Optional auto-start with Windows (covers wake-from-sleep automatically
  because the app stays running).
* A proper installed app entry with a working Uninstall button — no
  third-party installer software required.

---

## Files in this project

| File | Purpose |
|------|---------|
| `dateclock.py` | The application source code |
| `make_icon.py` | Generates the app icon |
| `requirements.txt` | Python packages the app depends on |
| `build.py` | The build script — open in Thonny and press F5 to build DateClock.exe |
| `build.bat` | Same as `build.py` but for double-clicking from File Explorer |
| `Install.bat` | Double-click to install DateClock onto your PC |
| `install.ps1` | The actual installer logic (invoked by `Install.bat`) |
| `Cleanup.bat` | Double-click to wipe a partial install (if `Uninstall` failed) |
| `cleanup.ps1` | The actual cleanup logic (invoked by `Cleanup.bat`) |
| `DEPLOY_GUIDE.md` | This file |

All these files must live together in a single folder, e.g.
`C:\Users\<you>\Documents\DateClock\`.

---

## Step 1 — Have a Python ready

You need any reasonably recent Python (3.10 or newer). `build.bat` will
look in three places and use the first one it finds:

1. The `py` launcher (the standard python.org installer puts it on PATH).
2. `python` anywhere on PATH.
3. **Thonny's bundled Python**, in `%LOCALAPPDATA%\Programs\Thonny\` or
   `Program Files\Thonny\`.

**If you have Thonny installed already, you're done — skip to Step 2.**
Thonny ships its own Python with `pip` included, and `build.bat` finds it
automatically without needing PATH changes.

If you don't have Thonny or a standalone Python yet, install one of:

* **Thonny** — easiest if you don't already use Python for other things.
  Download from <https://thonny.org>. Default install, no extra config.
* **Standalone Python** from <https://www.python.org/downloads/windows/>.
  Tick **"Add python.exe to PATH"** on the first screen of the installer.

---

## Step 2 — Put the files in place

1. Create a folder, e.g. `C:\Users\<you>\Documents\DateClock\`.
2. Copy all the files listed above into it.

---

## Step 3 — (Optional) Try the clock from source first

Good for confirming things work before spending time on the build.

1. Open Thonny → **File → Open…** → pick `dateclock.py`.
2. **Tools → Manage Packages…**, install:
   * `pystray`
   * `Pillow`
3. Press **F5**.
4. The clock appears top-right; a tray icon appears bottom-right.
5. Right-click the tray icon → **Settings…** to play with the new options.
6. To stop: tray icon → **Quit**.

---

## Step 4 — Build DateClock.exe

You have two equivalent ways to do this. Pick whichever you prefer.

### Option A — From Thonny (recommended)

1. Open Thonny → **File → Open…** → pick **`build.py`** in the DateClock
   folder.
2. Press **F5**.
3. The Shell pane shows live progress: dependencies installing, then
   PyInstaller running. The first run takes 1–3 minutes; subsequent runs
   are faster.
4. When you see **`Build complete`**, your EXE is at
   `dist\DateClock.exe`.

### Option B — From File Explorer

Double-click **`build.bat`**. It finds whatever Python is available
(including Thonny's bundled one) and runs `build.py` with it. A console
window stays open so you can read the output.

### Either way

You can double-click `dist\DateClock.exe` now to test the built version
without installing it. If something didn't work, the error message in
the Thonny Shell (or the console window) tells you what went wrong.

---

## Step 5 — Install DateClock onto your PC

This is the part that registers DateClock with Windows so it shows up in
**Settings → Apps → Installed apps**, can be launched from the Start Menu,
optionally starts with Windows, and has a real Windows-managed Uninstall
button — without needing any third-party installer software.

The installer installs **per-machine**, into `C:\Program Files\DateClock`,
so all user accounts on the PC see the same Start Menu entry, and the
Apps & Features listing is system-wide (the same way you'd see Chrome or
VLC). This requires administrator rights, which Windows will ask for
exactly once.

1. **Double-click `Install.bat`** in the DateClock folder.
2. Windows pops up a **UAC prompt** ("Do you want to allow this app to
   make changes to your device?"). Click **Yes**.
3. A new console window opens (running as administrator) and asks three
   questions:
   * **Create a desktop shortcut for all users?** (Y/N)
   * **Start DateClock automatically when YOU log in?** (Y/N) — even though
     the installer is running with admin rights, this option applies to
     *your* user account, not the Administrator account.
   * **Launch DateClock when installation finishes?** (Y/N)
   Press Enter to accept the default (Y) for each.
4. Done. DateClock is now installed to:
   ```
   C:\Program Files\DateClock\
   ```

### What just happened

`Install.bat` runs `install.ps1` with PowerShell. The script:

* Self-elevates with UAC if not already running as administrator.
* Stops any running `DateClock.exe` (across all users).
* Copies `dist\DateClock.exe` into `C:\Program Files\DateClock\`.
* Creates a Start Menu shortcut in the **All Users** Start Menu, so every
  account on this PC can find DateClock by pressing Win and typing it.
* Optionally creates a desktop shortcut on the **Public Desktop** (visible
  to every account).
* Optionally adds a `HKCU\…\Run` entry **in the original launching user's
  hive** (not the Administrator's), so DateClock starts at logon for that
  user. Other accounts on the PC don't get autostart unless they install it
  themselves.
* Writes the Windows Apps & Features registration under
  `HKLM\…\Uninstall\DateClock`. That's the registry key Windows reads to
  populate the Installed apps list, with the display name, version,
  publisher, install location, icon, and an UninstallString that points to
  the auto-generated `uninstall.ps1`.

---

## Step 6 — Confirm it's installed properly

1. Press **Win** and type `DateClock` — the Start Menu shortcut should appear.
2. Open **Settings → Apps → Installed apps** and search for **DateClock**.
   It should be there, showing version 1.0.0, with a `…` menu containing
   **Uninstall**.
3. If you ticked startup, restart Windows once. DateClock should appear
   automatically.

---

## Updating later

Whenever you change `dateclock.py`:

1. Re-run the build — either `build.py` in Thonny (F5) or `build.bat`.
   This overwrites `dist\DateClock.exe`.
2. Re-run `Install.bat`. It detects the running DateClock, stops it,
   overwrites the installed copy, and relaunches.

The Apps & Features entry stays the same — no duplicate installs.

---

## Uninstalling

You have two equivalent ways:

* **Settings → Apps → Installed apps → DateClock → ⋯ → Uninstall.** This is
  the normal Windows route. You'll get one UAC prompt (since the uninstaller
  needs to delete from Program Files), then Windows runs the same uninstall
  script the installer dropped onto your disk.
* Run `uninstall.ps1` directly from `C:\Program Files\DateClock\`. It also
  self-elevates if you launched it without admin rights.

Either way, the script removes the shortcuts, the startup entry, the
Apps & Features registration, and finally the install folder itself.

Your personal configuration in `%APPDATA%\DateClock\` is **left behind** so
that reinstalling later picks up where you left off. To wipe it completely,
delete that folder manually after uninstalling.

### If uninstall didn't fully clean up

If you deleted the install folder manually before Windows could run
`uninstall.ps1`, or the uninstall failed for any other reason, DateClock
will still appear in **Settings → Apps → Installed apps** because the
registry entry survives. To clean everything out:

**Double-click `Cleanup.bat`** from the project source folder. It self-
elevates, then sweeps:

* Registry entries (`HKLM` and `HKCU`) for both **DateClock** and (in case
  you'd installed under the older name) **BigClock**.
* Autostart entries in every loaded user hive.
* Shortcuts in all the standard locations (all-users Start Menu,
  per-user Start Menu, Public Desktop, your Desktop).
* Install folders that may have survived.
* Optionally, your `%APPDATA%\DateClock\` config (asks first).

The script prints a summary of everything it removed. After running, the
DateClock entry in Apps & Features disappears.

---

## Settings reference

Open via the tray icon → **Settings…**. Seven tabs:

### Font
| Option | Notes |
|--------|-------|
| Font family | Lists every Windows-installed font. Default is Cascadia Mono (monospaced — digit widths don't shift as time advances) |
| Font weight | normal / bold |
| Font size (px) | 20–400. Affects clock size overall |
| Use 24-hour | 12 vs 24 |
| Show AM/PM | Only applies in 12-hour mode |
| Show leading zero | `09:05` vs `9:05` |
| Show seconds | toggle |

### Colors
Each colour has its own opacity slider so digits and the separator can be styled completely independently.

| Option | Notes |
|--------|-------|
| Digit color / opacity | Digit colour and opacity |
| Separator color / opacity | Separator colour and opacity (the separator can be a different colour from the digits) |

### Effects
| Option | Notes |
|--------|-------|
| Text outline | Crisp coloured stroke around each digit. Useful when the background is messy |
| Outline thickness (px) | 0–20 |
| Text shadow | Soft shadow behind the digits |
| Shadow offset X/Y | Direction the shadow falls |
| Shadow blur (px) | Higher = softer |
| Shadow opacity | 0–1 |

### Separator
| Option | Notes |
|--------|-------|
| Style | **colon** (two dots), **dots** (single centred dot between numbers), **dash**, or **none** |
| Perfect circles | When on, colon/dots are mathematically circular ellipses; when off they're squares |
| Dot radius (% of font) | 2–30. Smaller = subtler dots |
| Vertical offset (% font) | -50…+50. Move dots up or down relative to the digits |
| Between digits (px) | Extra spacing between numbers |
| Around separator (px) | Extra spacing on each side of the separator |
| Blink interval (ms) | Time between flips. 0 = no blink (solid). |
| Transition duration (ms) | How long the colour fade itself takes. 0 = instant snap. Set this **lower than** the interval. E.g. interval 600 ms + transition 150 ms = clear blink with smooth-but-snappy fade. |
| Off color | The colour to fade *to* when "off". Set the same as the text color for no visible blink, or a contrasting dim grey for a classic blink |
| Blink applies to whole clock | When on, the whole time fades; otherwise only the separator |

### Date
A second row inside the clock's box. Can sit below or above the time.
Independently configurable.

| Option | Notes |
|--------|-------|
| Show date below time | Master toggle. Also available from the tray menu |
| Format | strftime-style. The dropdown offers presets — `Monday, 01 January 2026`, `01/06/2026`, `Mon, 01 Jan 2026`, etc. — but the field is free-text, so any `strftime` directive works. A live preview right below shows what your format renders to *now* |
| Font family | Defaults to "(inherit)" — same family as the time. Pick a different family from the dropdown to use a contrasting font |
| Font weight | normal / bold |
| Font size (px) | Used unless **Stretch date to match time width** is on |
| Stretch date to match time width | When on, the date's font size is auto-computed (via binary search) so the rendered string width equals the time's width. No glyph deformation — letters grow or shrink proportionally |
| Date color / opacity | Independent of the time's colour |
| Position | `below` (default) or `above`. Puts the date on the chosen side of the time, inside the same box |
| Gap from time (px) | Vertical space between the time and the date. Range -200 to 200. **Negative values pull them closer**, eating into the font's built-in vertical breathing room — useful when you want a tighter visual link than a font's ascender/descender naturally allows. Very negative values cause the rows to overlap |
| Alignment | left / center / right relative to the time's footprint |
| Horizontal offset (px) | Fine-tune on top of alignment. -300 to +300 |
| Letter spacing (px) | Extra space between every character. Useful with stretching, or for a wide spaced look |

The box auto-sizes to fit both rows. Inner padding settings apply around
the whole content, not each row.

### Calendar
A month-view popup appears when the cursor hovers the clock for 3 seconds.
Useful even with click-through enabled, since hovering doesn't require a
click. The popup has exactly three clickable controls — previous month,
next month, and the month/year header (click to enter year-step mode) —
plus the dates themselves: clicking any date dismisses the popup.

**Hover behaviour:** delay-to-open is configurable. The popup stays open
while the cursor is over either the clock or the calendar itself. Move
the cursor off both and it dismisses automatically. Dragging the clock
also dismisses the calendar.

| Group | Option | Notes |
|-------|--------|-------|
| Behavior | Enable calendar popup on hover | Master toggle. Also in the tray menu |
|          | Hover delay (ms) | 300–6000. Default 3000 |
|          | Hide time while calendar is open | If on, the clock becomes invisible whenever the calendar is showing |
| Placement | Expand toward | One of 8 directions relative to the clock box. `expand-down` puts the calendar below the clock; `expand-up-left` puts it diagonally above-left, etc. |
|           | Distance from clock (px) | Gap between the clock box and the calendar. -60 to 60; negative values let the calendar overlap the clock's edge |
| Font     | Family | `(blank)` inherits from the clock; otherwise pick any installed font |
|          | Weight | normal / bold |
|          | Font size (px) | 8–48 |
| Layout   | Cell padding X/Y | Inside each date cell |
|          | Row/column spacing | Between cells |
|          | Digit spacing within date | Extra px between the tens and ones digits of a 2-digit date |
|          | Show leading zeros | If off, single-digit dates are center-aligned in their cell |
| Week     | Week starts on | monday / sunday |
|          | Weekend days | none / sat-sun / sun-only / fri-sat |
|          | Highlight weekend | toggle |
|          | Highlight mode | background (tinted cell) or foreground (coloured digits) |
|          | Weekend color + opacity | Colour and alpha of the highlight |
| Colors   | Date number | Default digit colour |
|          | Today highlight | Ring around today's cell |
|          | Other-month | Colour for the leading/trailing dates of adjacent months |
|          | Header / weekday | Month-year header and the Mon/Tue/… row |
|          | Each with its own opacity slider | |
| Background & box | Background color + opacity | The popup's panel |
|                   | Rounded corners | toggle |
|                   | Corner radius | 0–40 px |
|                   | Outline color + thickness | Optional border around the panel |

### Box (background panel)
| Option | Notes |
|--------|-------|
| Enable background box | Master toggle |
| Box color | Fill colour |
| Box opacity | 0–1. The whole "background transparency" setting from v1 lives here now |
| Corner radius (px) | 0–100. 0 = sharp rectangle |
| Inner padding X/Y | Space between text and box edge. **Can be negative** (-80 to 100) — useful when a font has built-in vertical breathing room and you want the box to hug the visible glyphs more tightly. Going far enough negative will clip into the glyphs themselves |
| Outer padding X/Y | Empty space between the visible box and the window edge — useful if you also use a drop shadow that needs room |
| Box outline | A coloured border around the box |
| Outline thickness (px) | 0–20 |
| Box shadow | Drop shadow behind the box itself |
| Shadow offset / blur / opacity | Same idea as text shadow but for the panel |

### Position
| Option | Notes |
|--------|-------|
| Anchor | 9 choices. The clock grows away from the anchored corner / edge — set `top-right` and any size increase pushes the clock down and to the left |
| Margin X / Y | Distance from the anchored edge |
| Identify monitors | Pops a big number on each monitor for 3 seconds, the same way Windows' Display Settings does. Lets you see which physical screen is "#1", "#2", etc. |
| Move to current monitor | If you've used Anchor + Margin to position the clock and want this monitor remembered as the home screen, click this. Otherwise, dragging the clock with the mouse does the same thing automatically |

The Position tab shows which monitor the clock is currently anchored to,
along with the resolution and virtual-desktop position of every connected
monitor. When you drag the clock to a different monitor, both the new
position *and* the monitor identity are saved — so restarting or coming
back from hibernate puts the clock on the same screen it was on, not the
primary one.

You can also grab and drag the clock with the mouse if "Draggable" is on,
and the margins automatically update so the new position is preserved.

### Behavior
| Option | Notes |
|--------|-------|
| Always on top | |
| Click-through | Mouse clicks pass through the clock. The tray icon still works |
| Draggable | Allows dragging the clock with the mouse. Automatically **grayed out** while Click-through is enabled (a click-through window can't receive drag events). Your preference is remembered — turn click-through back off and Draggable returns to whatever you had it set to |
| Start with Windows | Toggles the registry entry |

A **Reset to defaults** button at the bottom restores every setting if you
make a mess.

---

## How the clock is rendered

The clock is drawn with **Pillow** (antialiased glyphs) and then pushed
straight to the Windows compositor with `UpdateLayeredWindow`. That means
Windows itself composites the antialiased edges against whatever's behind
the clock — no chroma-key trick, no halo around bright text on a transparent
background.

If you ever see fuzzy edges at huge sizes (say >300 px), it's because:

* The system font fallback kicked in. Make sure the font you picked is
  actually installed. The dropdown only lists installed fonts, and there's
  a "Loaded from" diagnostic right under the font picker.
* You enabled **Text shadow** with a high blur — that *is* the effect.

---

## Single instance, sleep / hibernation

* Trying to launch DateClock while it's already running silently exits.
* DateClock stays running through sleep and hibernation. When you wake the
  PC the clock is still there.
* "Start with Windows" handles the post-reboot case (e.g. after a
  Windows Update).

---

## Troubleshooting

**`build.bat` says "No Python installation found"** — install Thonny
(from <https://thonny.org>) and re-run the script; it auto-detects
Thonny's bundled Python. Or install standalone Python with **Add to PATH**
ticked.

**`pip install` fails** — open Command Prompt and run:
```
python -m pip install --upgrade pip
python -m pip install pystray Pillow pyinstaller
```

**Always-on-top stops working occasionally** — Windows can silently drop
the topmost z-order when other things happen (UAC prompts, fullscreen
games, resume from sleep). DateClock re-asserts topmost once per second to
recover automatically, so any disruption clears within ~1 second on its
own. If it doesn't recover, toggling the setting off-then-on forces a
fresh re-assert immediately.

**Font change has no effect / digits don't resize but separator does** —
Open Settings → Font tab. Just under the font dropdown there's a "Loaded
from" line. It shows what Pillow actually opened:
* `✓ filename.ttf` (green) — font loaded correctly. If size still doesn't
  change, restart DateClock once (the font cache is per-session).
* `⚠ Fell back to DejaVuSans` (red) — DateClock couldn't find a file for
  the family name you picked. Try a known-good Windows font: Consolas,
  Segoe UI, Arial, Calibri, Verdana, Courier New.
* `⚠ BITMAP-DEFAULT` (red) — both the registry lookup and Pillow's name
  resolver failed. Same fix: pick a different font.

**Can't drag the clock to the top of the screen** — fixed in this build.
Behind the scenes, the clock used to re-anchor itself every 50 ms which
fought against the drag. Now it only re-anchors when the rendered size
actually changes, and never while you're dragging.

**Dual monitor: clock jumps to the wrong screen** — fixed in this build.
DateClock now enumerates every monitor via Windows API. The "anchor"
positions (top-right, bottom-left, etc.) attach to whichever monitor
the clock is currently on. Drag the clock to your second monitor and
the next size change will keep it there, anchored to that monitor's
edges.

**Dual monitor: adaptive color is wrong on the secondary screen** —
also fixed. The screen-sampling code now uses `all_screens=True` so it
reads from the actual area behind the clock regardless of which monitor
that is.

**Tray icon missing** — click the up-arrow `^` in the taskbar and drag the
DateClock icon out to keep it visible.

**Clock looks fine but the box doesn't appear** — the box is off by default.
Open Settings → **Box** tab → tick **Enable background box** and bump
**Box opacity** above 0.

**Background is showing a strange near-black colour where you'd expect
transparency** — the transparency trick uses RGB `(1,2,3)` as the chroma key.
If you happen to pick a colour very close to that as your box colour,
shift it slightly.

**Click-through is on and I can't click the clock to bring up the menu** —
right-click the tray icon. Toggle "Click-through" off from there.

**Antivirus / SmartScreen warns about the unsigned EXE** — normal for any
self-built executable. Click "More info → Run anyway".

**The font I picked doesn't render correctly** — Pillow needs to find a
TTF file for the family. The dropdown only lists installed fonts, but if
Pillow can't find a matching file it falls back to a default. Stick to
well-known fonts (Consolas, Arial, Segoe UI, etc.) or install proper TTFs.

**Settings dialog doesn't fit on a small screen** — every tab is scrollable;
drag the dialog corners to resize.

**`Install.bat` flashes and disappears** — open a PowerShell window manually
and run `powershell -ExecutionPolicy Bypass -File install.ps1` to see the
error message. Common cause: `dist\DateClock.exe` doesn't exist yet because
`build.bat` hasn't been run, or DateClock is still running and locking the
EXE (close it from the tray icon first).

**Uninstall didn't fully clean up the folder** — the self-delete trick
waits 3 seconds for PowerShell to release the script file, then deletes
the install directory. If something else (your antivirus, an open File
Explorer window pointed at the folder, etc.) is holding the directory open,
the deletion fails. Close any open windows pointing at
`C:\Program Files\DateClock\` and delete it manually.

---

## File map

```
DateClock\
├── dateclock.py            ← edit to change behaviour
├── make_icon.py           ← edit to change the app icon
├── requirements.txt       ← Python dependencies for the build
├── build.py               ← run in Thonny (F5) to build DateClock.exe
├── build.bat              ← same as build.py, for double-clicking
├── Install.bat            ← double-click to install onto your PC
├── install.ps1            ← what Install.bat actually runs
├── DEPLOY_GUIDE.md        ← this file
├── dateclock.ico           ← generated during build
└── dist\DateClock.exe      ← generated during build
```

After installing, DateClock lives at:
```
C:\Program Files\DateClock\
├── DateClock.exe           ← the running program
└── uninstall.ps1          ← what the Windows Uninstall button runs
```

That's it — `Install.bat` gives you a fully featured, antialiased,
deeply customisable digital clock that integrates with Windows the same
way any other installed app does.

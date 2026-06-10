"""
DateClock build script — run this from Thonny (or any Python IDE) to
produce dist/DateClock.exe.

How it works:
    1. Installs the build dependencies (pystray, Pillow, pyinstaller) into
       the Python you're running this with. If you're in Thonny, that's
       Thonny's bundled Python — no PATH changes needed.
    2. Generates the application icon.
    3. Cleans previous build artifacts.
    4. Runs PyInstaller to produce dist/DateClock.exe.

In Thonny: File -> Open... -> build.py, then press F5. The Shell pane shows
all output as it happens. The whole process takes 1-3 minutes the first
time, and ~30 seconds on subsequent runs.
"""

import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ENTRY_SCRIPT = SCRIPT_DIR / "dateclock.py"
ICON_GENERATOR = SCRIPT_DIR / "make_icon.py"
ICON_FILE = SCRIPT_DIR / "dateclock.ico"
REQUIREMENTS = SCRIPT_DIR / "requirements.txt"
APP_NAME = "DateClock"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def section(title):
    print()
    print("=" * 66)
    print(f" {title}")
    print("=" * 66)


def run(cmd, **kwargs):
    """Run a command, streaming output to the Thonny Shell pane in
    real time. Raises RuntimeError on non-zero exit."""
    print(">", " ".join(str(c) for c in cmd))
    # We deliberately don't capture output so it streams live into Thonny.
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR), **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: "
                           f"{' '.join(str(c) for c in cmd)}")


def ensure_files_present():
    missing = []
    for path in (ENTRY_SCRIPT, ICON_GENERATOR, REQUIREMENTS):
        if not path.exists():
            missing.append(path.name)
    if missing:
        raise RuntimeError(
            "Missing files in the project folder: "
            + ", ".join(missing)
            + f"\nThis script expects to live next to: {ENTRY_SCRIPT.name}, "
              f"{ICON_GENERATOR.name}, {REQUIREMENTS.name}"
        )


# ---------------------------------------------------------------------------
# Main build steps
# ---------------------------------------------------------------------------
def install_dependencies():
    section("Step 1 / 4 — Installing build dependencies")
    print(f"Python:   {sys.executable}")
    print(f"Version:  {sys.version.split()[0]}")
    print()
    # Upgrade pip first; harmless if already current.
    try:
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    except RuntimeError as e:
        # Some Python installs ship without write access to pip itself
        # (Thonny does, but just in case). The package install below will
        # still work with the bundled pip version.
        print(f"  (skipping pip self-upgrade: {e})")

    run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def generate_icon():
    section("Step 2 / 4 — Generating application icon")
    try:
        run([sys.executable, str(ICON_GENERATOR)])
    except RuntimeError as e:
        print(f"  Icon generation failed: {e}")
        print("  Continuing without a custom icon.")
        return False
    return ICON_FILE.exists()


def clean_previous_build():
    section("Step 3 / 4 — Cleaning previous build artifacts")
    for name in ("build", "dist"):
        path = SCRIPT_DIR / name
        if path.exists():
            print(f"  Removing {path}")
            shutil.rmtree(path, ignore_errors=True)
    spec = SCRIPT_DIR / f"{APP_NAME}.spec"
    if spec.exists():
        print(f"  Removing {spec.name}")
        spec.unlink()
    print("  Done.")


def run_pyinstaller(have_icon):
    section("Step 4 / 4 — Building DateClock.exe with PyInstaller")
    print("This takes 1-3 minutes the first time. Subsequent builds are faster.")
    print()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
    ]
    if have_icon:
        cmd += ["--icon", str(ICON_FILE)]
    cmd += [str(ENTRY_SCRIPT)]
    run(cmd)


def main():
    print(f"DateClock build script")
    print(f"Working directory: {SCRIPT_DIR}")

    ensure_files_present()

    install_dependencies()
    have_icon = generate_icon()
    clean_previous_build()
    run_pyinstaller(have_icon)

    exe_path = SCRIPT_DIR / "dist" / f"{APP_NAME}.exe"
    section("Build complete")
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"  {exe_path}")
        print(f"  Size: {size_mb:.1f} MB")
        print()
        print("Next step: double-click Install.bat to install DateClock onto")
        print("your PC. You can also double-click the EXE directly to test.")
    else:
        # PyInstaller succeeded but the EXE isn't where we expect — odd.
        print("  Build reported success but the EXE was not found at:")
        print(f"  {exe_path}")
        print("  Check the PyInstaller output above for clues.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print()
        print("=" * 66)
        print(" BUILD FAILED")
        print("=" * 66)
        print(str(e))
        # Exit code so Thonny shows the script as failed
        sys.exit(1)

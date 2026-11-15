#!/bin/sh
# Core tests (the Windows rules, under Mono) and the Linux tests.
# The same groups and command lines as the CI job "linux" (.github/workflows/build.yml).
# A missing package skips a test here. CI sets DESKTOP_RECORDER_REQUIRE_GUI=1, so it fails there.
# The GUI tests always run in their own Xvfb, never on the live desktop.
set -eu
cd "$(dirname "$0")"

# 1. Unit tests
env -u DISPLAY PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_linux*.py' -v
PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_pdeathsig.py' -v
PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_gst_pipeline.py' -v

# 2. Core tests (Mono)
mcs -sdk:4.5 -nologo -target:exe -out:/tmp/desktop-recorder-tests.exe \
  tests/CoreTests.cs RecorderCore.cs RecordingSession.cs
mono /tmp/desktop-recorder-tests.exe

# 3. GUI tests, in their own Xvfb
if ! command -v xvfb-run >/dev/null 2>&1; then
  echo "GUI tests skipped: xvfb-run is missing."
  exit 0
fi
if command -v dbus-run-session >/dev/null 2>&1; then
  dbus-run-session -- xvfb-run -a -s "-screen 0 1280x800x24" env PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_x11*.py' -v
else
  xvfb-run -a -s "-screen 0 1280x800x24" env PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_x11*.py' -v
fi

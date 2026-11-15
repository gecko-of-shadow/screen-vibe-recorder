"""Unit tests for settings.py (section 4 of linux/design/DESIGN.md). Pure: they run on Windows too."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from desktop_recorder.geometry import Rect
from desktop_recorder.settings import (
    DEFAULT_FPS,
    Settings,
    clamp_cq,
    copy_settings,
    load_settings,
    parse_settings,
    region_text,
    runtime_dir,
    save_settings,
    serialize_settings,
)

WINDOWS_KEYS = [
    "folder",
    "fps",
    "quality",
    "split_minutes",
    "record_on_launch",
    "copy_to_clipboard",
    "play_sounds",
    "show_pointer",
    "hotkey",
    "capture_backend",
    "encoder",
    "chroma",
    "frame_rate_mode",
    "nvenc_cq",
    "selector_crosshair",
    "selector_magnifier",
    "selector_position",
    "region",
    "last_region",
]

LINUX_KEYS = [
    "record_audio",
    "start_on_login",
    "wayland_restore_token",
    "wayland_region",
    "wayland_frame",
]


def keys_of(text: str) -> list[str]:
    return [line.split("=", 1)[0] for line in text.split("\n") if line]


class SettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        s = Settings()
        self.assertEqual(s.fps, 10.0)
        self.assertEqual(DEFAULT_FPS, 10.0)
        self.assertEqual(s.frame_rate_mode, "changes")
        self.assertEqual(s.quality, 1)
        self.assertTrue(s.show_pointer)
        self.assertEqual(s.encoder, "auto")
        self.assertEqual(s.nvenc_cq, 23)
        self.assertEqual(s.chroma, "yuv420")
        self.assertEqual(s.capture_backend, "ddagrab")
        self.assertEqual(s.hotkey_text, "Win+Shift+D")
        self.assertEqual(s.region, Rect())
        self.assertEqual(s.wayland_region, (0, 0, 0, 0, 0, 0))
        self.assertTrue(s.wayland_frame)
        self.assertTrue(s.folder.endswith("Recordings"))
        # An empty file gives the same values.
        p = parse_settings("")
        self.assertEqual(serialize_settings(p), serialize_settings(s))

    def test_nan_fps_gives_10(self) -> None:
        for text in ("fps=NaN", "fps=nan", "fps=inf", "fps=-inf"):
            s = parse_settings(text, Settings(fps=4.0))
            self.assertEqual(s.fps, 10.0, text)
        self.assertEqual(parse_settings("fps=0.01").fps, 0.2)
        self.assertEqual(parse_settings("fps=500").fps, 60.0)
        self.assertEqual(parse_settings("fps=abc", Settings(fps=4.0)).fps, 4.0)

    def test_bad_known_value_keeps_old_and_is_not_extra(self) -> None:
        old = Settings(encoder="libx264", capture_backend="gdigrab", chroma="yuv444", frame_rate_mode="fixed")
        s = parse_settings(
            "encoder=h264_vaapi\ncapture_backend=x11grab\nchroma=yuv422\nframe_rate_mode=vfr\nquality=x\nnvenc_cq=",
            old,
        )
        self.assertEqual(s.encoder, "libx264")
        self.assertEqual(s.capture_backend, "gdigrab")
        self.assertEqual(s.chroma, "yuv444")
        self.assertEqual(s.frame_rate_mode, "fixed")
        self.assertEqual(s.quality, 1)
        self.assertEqual(s.nvenc_cq, 23)
        self.assertEqual(s.extra_lines, [])
        # Defaults stay when the file has a bad value.
        d = parse_settings("encoder=h264_vaapi\ncapture_backend=x11grab")
        self.assertEqual(d.encoder, "auto")
        self.assertEqual(d.capture_backend, "ddagrab")
        self.assertEqual(d.extra_lines, [])
        # The values that are accepted.
        g = parse_settings("encoder=h264_nvenc\ncapture_backend=gdigrab\nchroma=yuv444\nframe_rate_mode=fixed")
        self.assertEqual(
            (g.encoder, g.capture_backend, g.chroma, g.frame_rate_mode),
            ("h264_nvenc", "gdigrab", "yuv444", "fixed"),
        )

    def test_dropped_keys(self) -> None:
        s = parse_settings("stop_hotkey=Win+Shift+S\nlast_region_hotkey=Win+Shift+R\nhotkey=Ctrl+Alt+F5")
        self.assertEqual(s.extra_lines, [])
        self.assertEqual(s.hotkey_text, "Ctrl+Alt+F5")
        text = serialize_settings(s)
        self.assertNotIn("stop_hotkey", text)
        self.assertNotIn("last_region_hotkey", text)

    def test_eq_rule(self) -> None:
        s = parse_settings("=x\nnoequals\n  spaced line  \nunknown_key = value \nfolder=/tmp/a=b")
        self.assertEqual(s.extra_lines, ["=x", "noequals", "spaced line", "unknown_key=value"])
        self.assertEqual(s.folder, "/tmp/a=b")
        # A key with spaces before "=" is still a key.
        t = parse_settings("  quality = 2")
        self.assertEqual(t.quality, 2)
        self.assertEqual(t.extra_lines, [])

    def test_region_rules(self) -> None:
        old = Settings(region=Rect(5, 6, 100, 200), last_region=Rect(1, 1, 10, 10))
        s = parse_settings("region=1,2,3\nlast_region=1,2,3,4,5", old)
        self.assertEqual(s.region, Rect(5, 6, 100, 200))
        self.assertEqual(s.last_region, Rect(1, 1, 10, 10))
        s = parse_settings("region=1,2,0,5\nlast_region=7,8,9,-1", old)
        self.assertEqual(s.region, Rect(0, 0, 0, 0))
        self.assertEqual(s.last_region, Rect(0, 0, 0, 0))
        s = parse_settings("region= -10 , 20 ,982, 430\nlast_region=a,b,c,d", old)
        self.assertEqual(s.region, Rect(-10, 20, 982, 430))
        self.assertEqual(s.last_region, Rect(1, 1, 10, 10))
        self.assertEqual(s.extra_lines, [])
        self.assertEqual(region_text(Rect(-10, 20, 982, 430)), "-10,20,982,430")
        self.assertIn("\nregion=-10,20,982,430\n", serialize_settings(s))
        # A Rect with a zero size is written as zeros.
        self.assertIn("\nregion=0,0,0,0\n", serialize_settings(Settings(region=Rect(3, 4, 0, 9))))

    def test_wayland_region_six_ints(self) -> None:
        s = parse_settings("wayland_region=1920,0,10,20,640,480")
        self.assertEqual(s.wayland_region, (1920, 0, 10, 20, 640, 480))
        self.assertIn("\nwayland_region=1920,0,10,20,640,480\n", serialize_settings(s))
        old = Settings(wayland_region=(1, 2, 3, 4, 5, 6))
        self.assertEqual(parse_settings("wayland_region=1,2,3,4,5", old).wayland_region, (1, 2, 3, 4, 5, 6))
        self.assertEqual(parse_settings("wayland_region=1,2,3,4,5,6,7", old).wayland_region, (1, 2, 3, 4, 5, 6))
        self.assertEqual(parse_settings("wayland_region=1,2,3,4,x,6", old).wayland_region, (1, 2, 3, 4, 5, 6))
        self.assertEqual(parse_settings("wayland_region=1,2,3,4,0,6", old).wayland_region, (0, 0, 0, 0, 0, 0))
        self.assertEqual(parse_settings("wayland_region=1,2,3,4,5,-6", old).wayland_region, (0, 0, 0, 0, 0, 0))
        self.assertEqual(parse_settings("wayland_region=1,2,3,4,5", old).extra_lines, [])

    def test_write_order_matches_windows(self) -> None:
        s = parse_settings("zeta=1\nfolder=/x\nnoequals\n")
        keys = keys_of(serialize_settings(s))
        self.assertEqual(keys[:19], WINDOWS_KEYS)
        self.assertEqual(keys[19:24], LINUX_KEYS)
        self.assertEqual(keys[24:], ["zeta", "noequals"])
        text = serialize_settings(Settings(folder="/home/u/Recordings"))
        self.assertTrue(
            text.startswith(
                "folder=/home/u/Recordings\nfps=10\nquality=1\nsplit_minutes=30\n"
                "record_on_launch=1\ncopy_to_clipboard=1\nplay_sounds=1\nshow_pointer=1\n"
                "hotkey=Win+Shift+D\ncapture_backend=ddagrab\nencoder=auto\nchroma=yuv420\n"
                "frame_rate_mode=changes\nnvenc_cq=23\nselector_crosshair=0\nselector_magnifier=1\n"
                "selector_position=1\nregion=0,0,0,0\nlast_region=0,0,0,0\n"
                "record_audio=1\nstart_on_login=0\nwayland_restore_token=\n"
                "wayland_region=0,0,0,0,0,0\nwayland_frame=1\n"
            ),
            text,
        )
        self.assertNotIn("\r", text)
        self.assertIn("fps=2.5\n", serialize_settings(Settings(fps=2.5)))
        self.assertIn("fps=0.333\n", serialize_settings(Settings(fps=1 / 3)))

    def test_round_trip(self) -> None:
        s = Settings(
            folder="/home/u/Videos rec",
            fps=12.5,
            quality=2,
            split_minutes=0,
            record_on_launch=False,
            copy_to_clipboard=False,
            play_sounds=False,
            show_pointer=False,
            hotkey_modifiers=2 | 1,
            hotkey_key="F9",
            capture_backend="gdigrab",
            encoder="libx264",
            chroma="yuv444",
            frame_rate_mode="fixed",
            nvenc_cq=17,
            selector_crosshair=True,
            selector_magnifier=False,
            selector_position=False,
            region=Rect(10, 20, 640, 480),
            last_region=Rect(0, 0, 1920, 1080),
            record_audio=False,
            start_on_login=True,
            wayland_restore_token="abc-123",
            wayland_region=(1920, 0, 2, 4, 800, 600),
            wayland_frame=False,
            extra_lines=["future_key=5", "free text"],
        )
        text = serialize_settings(s)
        again = parse_settings(text)
        self.assertEqual(again, s)
        self.assertEqual(serialize_settings(again), text)
        # A second parse with the same defaults does not add the extra lines two times.
        self.assertEqual(parse_settings(text, again).extra_lines, ["future_key=5", "free text"])
        # copy_settings is a deep copy.
        c = copy_settings(s)
        self.assertEqual(c, s)
        c.extra_lines.append("x=1")
        self.assertEqual(s.extra_lines, ["future_key=5", "free text"])
        # Save and load through a file: LF only, no BOM, no temp file left.
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "sub", "settings.txt")
            save_settings(s, path)
            with open(path, "rb") as handle:
                data = handle.read()
            self.assertNotIn(b"\r", data)
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(data.decode("utf-8"), text)
            self.assertFalse(os.path.exists(path + ".tmp"))
            self.assertEqual(load_settings(path), s)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_windows_crlf_file_parses(self) -> None:
        text = (
            "folder=C:\\Users\\Bran\\Videos\r\nfps=4\r\nquality=0\r\nsplit_minutes=15\r\n"
            "record_on_launch=0\r\ncopy_to_clipboard=1\r\nplay_sounds=0\r\nshow_pointer=0\r\n"
            "hotkey=Win+Shift+D\r\ncapture_backend=gdigrab\r\nencoder=h264_nvenc\r\nchroma=yuv444\r\n"
            "frame_rate_mode=fixed\r\nnvenc_cq=28\r\nselector_crosshair=1\r\nselector_magnifier=0\r\n"
            "selector_position=0\r\nregion=440,172,982,430\r\nlast_region=0,0,1920,1080\r\n"
            "custom=1\r\nold mac line\rlast\r\n"
        )
        s = parse_settings(text)
        self.assertEqual(s.folder, "C:\\Users\\Bran\\Videos")
        self.assertEqual(s.fps, 4.0)
        self.assertEqual(s.quality, 0)
        self.assertEqual(s.split_minutes, 15)
        self.assertFalse(s.record_on_launch)
        self.assertTrue(s.copy_to_clipboard)
        self.assertFalse(s.play_sounds)
        self.assertFalse(s.show_pointer)
        self.assertEqual(s.capture_backend, "gdigrab")
        self.assertEqual(s.encoder, "h264_nvenc")
        self.assertEqual(s.chroma, "yuv444")
        self.assertEqual(s.frame_rate_mode, "fixed")
        self.assertEqual(s.nvenc_cq, 28)
        self.assertTrue(s.selector_crosshair)
        self.assertFalse(s.selector_magnifier)
        self.assertFalse(s.selector_position)
        self.assertEqual(s.region, Rect(440, 172, 982, 430))
        self.assertEqual(s.last_region, Rect(0, 0, 1920, 1080))
        self.assertEqual(s.extra_lines, ["custom=1", "old mac line", "last"])
        # Linux-only keys keep their defaults.
        self.assertTrue(s.record_audio)
        self.assertTrue(s.wayland_frame)
        out = serialize_settings(s)
        self.assertNotIn("\r", out)
        self.assertIn("\ncapture_backend=gdigrab\n", out)
        # A file with a UTF-8 BOM (written by another tool) still loads.
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "settings.txt")
            with open(path, "wb") as handle:
                handle.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
            loaded = load_settings(path)
            self.assertEqual(loaded.folder, "C:\\Users\\Bran\\Videos")
            self.assertEqual(loaded.extra_lines, ["custom=1", "old mac line", "last"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_int_rule_ascii_only(self) -> None:
        old = Settings(quality=1, nvenc_cq=23, split_minutes=30)
        for text in ("quality=1_0", "quality=\u0661", "nvenc_cq=2_3", "split_minutes=1.5", "quality=0x1"):
            s = parse_settings(text, old)
            self.assertEqual((s.quality, s.nvenc_cq, s.split_minutes), (1, 23, 30), text)
            self.assertEqual(s.extra_lines, [], text)
        self.assertEqual(parse_settings("quality= +2 ", old).quality, 2)
        self.assertEqual(parse_settings("quality=-5", old).quality, 0)
        self.assertEqual(parse_settings("nvenc_cq=0", old).nvenc_cq, 1)
        self.assertEqual(parse_settings("nvenc_cq=99", old).nvenc_cq, 51)
        self.assertEqual(parse_settings("split_minutes=9999", old).split_minutes, 1440)
        self.assertEqual(parse_settings("region=1_0,2,3,4", Settings(region=Rect(1, 1, 2, 2))).region, Rect(1, 1, 2, 2))
        self.assertEqual(
            parse_settings("wayland_region=0,0,0,0,\u0661,2", Settings(wayland_region=(1, 2, 3, 4, 5, 6))).wayland_region,
            (1, 2, 3, 4, 5, 6),
        )
        self.assertEqual(clamp_cq(-3), 1)

    def test_load_bad_file_gives_defaults(self) -> None:
        folder = tempfile.mkdtemp()
        try:
            bad = os.path.join(folder, "bad.txt")
            with open(bad, "wb") as handle:
                handle.write(b"fps=4\nfolder=\xff\xfe\xc3\x28\n")
            self.assertEqual(serialize_settings(load_settings(bad)), serialize_settings(Settings()))
            as_folder = os.path.join(folder, "dir.txt")
            os.makedirs(as_folder)
            self.assertEqual(serialize_settings(load_settings(as_folder)), serialize_settings(Settings()))
            missing = os.path.join(folder, "missing.txt")
            self.assertEqual(serialize_settings(load_settings(missing)), serialize_settings(Settings()))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_runtime_dir_rule(self) -> None:
        saved = {k: os.environ.get(k) for k in ("XDG_RUNTIME_DIR", "XDG_CONFIG_HOME")}
        folder = tempfile.mkdtemp()
        try:
            os.environ["XDG_CONFIG_HOME"] = os.path.join(folder, "cfg")
            os.environ["XDG_RUNTIME_DIR"] = folder
            self.assertEqual(runtime_dir(), os.path.join(folder, "desktop-recorder"))
            self.assertFalse(os.path.exists(runtime_dir()))
            os.environ["XDG_RUNTIME_DIR"] = os.path.join(folder, "not-there")
            self.assertEqual(runtime_dir(), os.path.join(folder, "cfg", "DesktopRecorder"))
            del os.environ["XDG_RUNTIME_DIR"]
            self.assertEqual(runtime_dir(), os.path.join(folder, "cfg", "DesktopRecorder"))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

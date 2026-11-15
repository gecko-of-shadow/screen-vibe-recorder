"""FFmpeg argv, plan and fallback rules (spec 5.2 to 5.4). Pure: runs on Windows too."""

from __future__ import annotations

import unittest
from datetime import datetime

from desktop_recorder.ffmpeg_cmd import (
    NOTE_REGION_OFF_SCREEN,
    CapturePlan,
    choose_fallback,
    plan_wayland,
    plan_x11,
    wayland_argv,
    x11_argv,
)
from desktop_recorder.geometry import Rect
from desktop_recorder.settings import Settings

WHEN = datetime(2026, 11, 14, 10, 20, 30, 456000)
SCREEN = Rect(0, 0, 1280, 800)


def make_settings(**kw: object) -> Settings:
    base: dict[str, object] = dict(
        folder="/home/me/Recordings",
        fps=10.0,
        quality=1,
        frame_rate_mode="fixed",
        chroma="yuv420",
        show_pointer=True,
        split_minutes=0,
        encoder="auto",
        nvenc_cq=23,
    )
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def x264_plan(region: Rect | None = Rect(100, 100, 300, 200), w: int = 300, h: int = 200) -> CapturePlan:
    return CapturePlan("x11grab", "libx264", region, w, h, ())


def nvenc_plan(region: Rect | None = Rect(100, 100, 300, 200), w: int = 300, h: int = 200) -> CapturePlan:
    return CapturePlan("x11grab", "h264_nvenc", region, w, h, ())


def joined(argv: list[str]) -> str:
    return " ".join(argv) + " "


class ArgvTests(unittest.TestCase):
    def test_golden_argv_1(self) -> None:
        argv = x11_argv(make_settings(), x264_plan(), WHEN, ":0", None, "ffmpeg")
        expected = (
            "ffmpeg -hide_banner -loglevel error -stats -y -thread_queue_size 128 -f x11grab -framerate 10 "
            "-draw_mouse 1 -fpsprobesize 0 -probesize 32 -analyzeduration 0 -video_size 300x200 -i :0.0+100,100 -fps_mode cfr -c:v libx264 -preset veryfast "
            "-tune stillimage -crf 27 -x264-params rc-lookahead=20 -threads 10 -g 300 -pix_fmt yuv420p "
            "-movflags +frag_keyframe+empty_moov -frag_duration 2000000 -flush_packets 1 "
            "/home/me/Recordings/desktop_2026-11-14_10-20-30_456.mp4"
        )
        self.assertEqual(" ".join(argv), expected)
        self.assertTrue(all(isinstance(a, str) for a in argv))

    def test_whole_screen_changes_nvenc(self) -> None:
        s = make_settings(frame_rate_mode="changes")
        text = joined(x11_argv(s, nvenc_plan(None, 1280, 800), WHEN, ":0", None, "ffmpeg"))
        self.assertIn(
            " -vf crop=trunc(iw/2)*2:trunc(ih/2)*2:0:0,format=yuv420p,mpdecimate=hi=256:lo=128:frac=0.33:max=9 -fps_mode vfr "
            "-c:v h264_nvenc -preset p4 -rc vbr -cq 23 -b:v 0 -g 300 ",
            text,
        )
        self.assertIn(" -i :0.0 ", text)
        self.assertNotIn("-video_size", text)
        self.assertNotIn("-pix_fmt", text)

    def test_nvenc_444_fixed_and_changes(self) -> None:
        fixed = joined(x11_argv(make_settings(chroma="yuv444"), nvenc_plan(), WHEN, ":0", None, "ffmpeg"))
        self.assertIn(" -profile:v high444p -rgb_mode yuv444 -g 300 ", fixed)
        changes = joined(x11_argv(make_settings(chroma="yuv444", frame_rate_mode="changes"), nvenc_plan(),
                                  WHEN, ":0", None, "ffmpeg"))
        self.assertIn(" -vf format=yuv444p,mpdecimate=hi=256:lo=128:frac=0.33:max=9 ", changes)
        self.assertNotIn("-rgb_mode", changes)
        self.assertIn(" -profile:v high444p -g 300 ", changes)

    def test_nvenc_split(self) -> None:
        text = joined(x11_argv(make_settings(split_minutes=5), nvenc_plan(), WHEN, ":0", None, "ffmpeg"))
        self.assertIn(
            " -force_key_frames expr:gte(t,n_forced*300) -forced-idr 1 -f segment -segment_time 300 "
            "-segment_format mp4 ",
            text,
        )

    def test_x264_split_has_no_forced_idr(self) -> None:
        text = joined(x11_argv(make_settings(split_minutes=5), x264_plan(), WHEN, ":0", None, "ffmpeg"))
        self.assertIn(" -force_key_frames expr:gte(t,n_forced*300) -f segment ", text)
        self.assertNotIn("-forced-idr", text)

    def test_percent_folder(self) -> None:
        split = x11_argv(make_settings(folder="/home/me/100%done", split_minutes=1), x264_plan(), WHEN, ":0",
                         None, "ffmpeg")
        self.assertEqual(split[-1], "/home/me/100%%done/desktop_2026-11-14_10-20-30_456_%03d.mp4")
        plain = x11_argv(make_settings(folder="/home/me/100%done"), x264_plan(), WHEN, ":0", None, "ffmpeg")
        self.assertEqual(plain[-1], "/home/me/100%done/desktop_2026-11-14_10-20-30_456.mp4")

    def test_wayland_changes_x264(self) -> None:
        s = make_settings(frame_rate_mode="changes")
        plan = CapturePlan("pipewire", "libx264", Rect(0, 0, 1120, 892), 1120, 892, ())
        text = joined(wayland_argv(s, plan, WHEN, None, "ffmpeg"))
        self.assertIn(
            " -f rawvideo -pixel_format bgr0 -video_size 1120x892 -framerate 10 -fpsprobesize 0 -probesize 32 -analyzeduration 0 -i pipe:0 "
            "-vf format=yuv420p,mpdecimate=hi=256:lo=128:frac=0.33:max=9 -fps_mode vfr -c:v libx264 ",
            text,
        )
        self.assertNotIn("-draw_mouse", text)

    def test_wayland_audio_shortest(self) -> None:
        plan = CapturePlan("pipewire", "libx264", Rect(0, 0, 640, 480), 640, 480, ())
        text = joined(wayland_argv(make_settings(), plan, WHEN, "mon.monitor", "ffmpeg"))
        self.assertIn(" -i pipe:0 -thread_queue_size 1024 -f pulse -i mon.monitor -shortest -fps_mode cfr ", text)
        self.assertIn(" -pix_fmt yuv420p -c:a aac -b:a 128k -movflags ", text)

    def test_quality_cq(self) -> None:
        q0 = joined(x11_argv(make_settings(quality=0), nvenc_plan(), WHEN, ":0", None, "ffmpeg"))
        q2 = joined(x11_argv(make_settings(quality=2), nvenc_plan(), WHEN, ":0", None, "ffmpeg"))
        self.assertIn(" -cq 28 ", q0)
        self.assertIn(" -cq 17 ", q2)
        high = joined(x11_argv(make_settings(quality=0, nvenc_cq=50), nvenc_plan(), WHEN, ":0", None, "ffmpeg"))
        self.assertIn(" -cq 51 ", high)

    def test_x264_crf(self) -> None:
        self.assertIn(" -crf 32 ", joined(x11_argv(make_settings(quality=0), x264_plan(), WHEN, ":0", None, "f")))
        self.assertIn(" -crf 21 ", joined(x11_argv(make_settings(quality=2), x264_plan(), WHEN, ":0", None, "f")))

    def test_hidden_pointer(self) -> None:
        text = joined(x11_argv(make_settings(show_pointer=False), x264_plan(), WHEN, ":0", None, "ffmpeg"))
        self.assertIn(" -draw_mouse 0 ", text)

    def test_x11grab_queue_128(self) -> None:
        argv = x11_argv(make_settings(), x264_plan(), WHEN, ":1", "mon.monitor", "ffmpeg")
        text = joined(argv)
        self.assertIn(" -thread_queue_size 128 -f x11grab ", text)
        self.assertIn(" -i :1.0+100,100 -thread_queue_size 1024 -f pulse -i mon.monitor ", text)
        self.assertNotIn("-shortest", text)

    def test_no_nostats(self) -> None:
        x11 = x11_argv(make_settings(), x264_plan(), WHEN, ":0", None, "ffmpeg")
        plan = CapturePlan("pipewire", "libx264", Rect(0, 0, 640, 480), 640, 480, ())
        way = wayland_argv(make_settings(), plan, WHEN, None, "ffmpeg")
        for argv in (x11, way):
            self.assertNotIn("-nostats", argv)
            self.assertIn("-stats", argv)

    def test_fractional_fps(self) -> None:
        text = joined(x11_argv(make_settings(fps=2.5), x264_plan(), WHEN, ":0", None, "ffmpeg"))
        self.assertIn(" -framerate 2.5 ", text)
        self.assertIn(" -g 75 ", text)
        self.assertIn(" rc-lookahead=5 ", " " + text)  # round(5.0)
        self.assertIn(" -threads 3 ", text)


class PlanTests(unittest.TestCase):
    def test_plan_nvenc_limits(self) -> None:
        big = Rect(0, 0, 8192, 2160)
        # 4098 wide: make_even keeps 4098, over the 4096 limit.
        plan = plan_x11(make_settings(), Rect(0, 0, 4098, 1000), big, nvenc_ok=True)
        self.assertEqual(plan.encoder, "libx264")
        self.assertEqual(plan.notes, ("NVENC cannot encode 4098x1000 (maximum 4096 px). libx264 records it.",))
        # 4097 wide becomes 4096 after make_even, which NVENC accepts.
        plan = plan_x11(make_settings(), Rect(0, 0, 4097, 1000), big, nvenc_ok=True)
        self.assertEqual(plan.encoder, "h264_nvenc")
        self.assertEqual(plan.width, 4096)
        self.assertEqual(plan.notes, ())
        # 140 wide is too small. The check also applies to an explicit h264_nvenc.
        plan = plan_x11(make_settings(encoder="h264_nvenc"), Rect(10, 10, 140, 300), SCREEN, nvenc_ok=False)
        self.assertEqual(plan.encoder, "libx264")
        self.assertEqual(plan.notes, ("NVENC cannot encode 140x300 (too small). libx264 records it.",))
        # 146 x 50 is the minimum that NVENC accepts.
        plan = plan_x11(make_settings(), Rect(10, 10, 146, 50), SCREEN, nvenc_ok=True)
        self.assertEqual(plan.encoder, "h264_nvenc")
        # Wayland uses the same rule.
        way = plan_wayland(make_settings(), Rect(0, 0, 140, 300), nvenc_ok=True)
        self.assertEqual((way.backend, way.encoder), ("pipewire", "libx264"))
        self.assertEqual(len(way.notes), 1)

    def test_plan_auto_without_nvenc_is_x264(self) -> None:
        plan = plan_x11(make_settings(), Rect(100, 100, 300, 200), SCREEN, nvenc_ok=False)
        self.assertEqual(plan.encoder, "libx264")
        self.assertEqual(plan.notes, ())
        self.assertEqual(plan_x11(make_settings(), Rect(100, 100, 300, 200), SCREEN, True).encoder, "h264_nvenc")
        forced = plan_x11(make_settings(), Rect(100, 100, 300, 200), SCREEN, True, force_x264=True)
        self.assertEqual(forced.encoder, "libx264")
        forced = plan_x11(make_settings(encoder="h264_nvenc"), Rect(100, 100, 300, 200), SCREEN, True,
                          force_x264=True)
        self.assertEqual(forced.encoder, "libx264")
        self.assertEqual(plan_x11(make_settings(encoder="libx264"), None, SCREEN, True).encoder, "libx264")
        self.assertEqual(plan_x11(make_settings(encoder="h264_nvenc"), Rect(100, 100, 300, 200), SCREEN,
                                  False).encoder, "h264_nvenc")

    def test_plan_region_offscreen_note(self) -> None:
        plan = plan_x11(make_settings(), Rect(2000, 2000, 300, 200), SCREEN, nvenc_ok=True)
        self.assertIsNone(plan.region)
        self.assertEqual((plan.width, plan.height), (1280, 800))
        self.assertEqual(plan.notes, (NOTE_REGION_OFF_SCREEN,))

    def test_offscreen_note_before_nvenc_note(self) -> None:
        screen = Rect(0, 0, 5000, 3000)
        plan = plan_x11(make_settings(), Rect(9000, 9000, 300, 200), screen, nvenc_ok=True)
        self.assertEqual(plan.encoder, "libx264")
        self.assertEqual(plan.notes[0], NOTE_REGION_OFF_SCREEN)
        self.assertEqual(plan.notes[1], "NVENC cannot encode 5000x3000 (maximum 4096 px). libx264 records it.")

    def test_plan_no_region_no_note(self) -> None:
        plan = plan_x11(make_settings(), None, Rect(0, 0, 1281, 801), nvenc_ok=False)
        self.assertIsNone(plan.region)
        self.assertEqual((plan.width, plan.height), (1280, 800))
        self.assertEqual(plan.notes, ())
        self.assertEqual(plan.backend, "x11grab")
        empty = plan_x11(make_settings(), Rect(), SCREEN, nvenc_ok=False)
        self.assertIsNone(empty.region)
        self.assertEqual(empty.notes, ())

    def test_plan_full_screen_region_is_none(self) -> None:
        plan = plan_x11(make_settings(), Rect(0, 0, 1280, 800), SCREEN, nvenc_ok=False)
        self.assertIsNone(plan.region)
        self.assertEqual(plan.notes, ())
        odd = Rect(0, 0, 1281, 801)
        self.assertIsNone(plan_x11(make_settings(), odd, odd, nvenc_ok=False).region)

    def test_plan_partial_region_clipped_and_even(self) -> None:
        plan = plan_x11(make_settings(), Rect(1100, 700, 301, 201), SCREEN, nvenc_ok=False)
        self.assertEqual(plan.region, Rect(1100, 700, 180, 100))
        self.assertEqual((plan.width, plan.height), (180, 100))
        self.assertEqual(plan.notes, ())

    def test_plan_wayland_keeps_crop(self) -> None:
        crop = Rect(8, 120, 1120, 892)
        plan = plan_wayland(make_settings(), crop, nvenc_ok=True)
        self.assertEqual(plan, CapturePlan("pipewire", "h264_nvenc", crop, 1120, 892, ()))


class FallbackTests(unittest.TestCase):
    def test_fallback_rules(self) -> None:
        auto = make_settings(encoder="auto")
        plan = nvenc_plan()
        # Rule 1: an NVENC error.
        self.assertEqual(choose_fallback(plan, auto, "[h264_nvenc] OpenEncodeSessionEx failed", 500),
                         (True, "NVENC failed. Recording again with libx264."))
        self.assertEqual(choose_fallback(plan, auto, "Cannot load libCUDA.so.1", 10000),
                         (True, "NVENC failed. Recording again with libx264."))
        # Rule 3: another error with NVENC from "auto".
        self.assertEqual(choose_fallback(plan, auto, "x11grab: cannot open display", 500),
                         (True, "FFmpeg failed with NVENC. Recording again with libx264."))
        # An explicit h264_nvenc gets no fallback.
        self.assertIsNone(choose_fallback(plan, make_settings(encoder="h264_nvenc"), "nvenc error", 500))
        # Too late.
        self.assertIsNone(choose_fallback(plan, auto, "nvenc error", 10001))
        # x264 has no fallback.
        self.assertIsNone(choose_fallback(x264_plan(), auto, "nvenc error", 500))


if __name__ == "__main__":
    unittest.main()

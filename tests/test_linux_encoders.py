"""NVENC probe rules (spec 5.5). Pure: a fake runner, no FFmpeg. Runs on Windows too."""

from __future__ import annotations

import subprocess
import threading
import unittest

from desktop_recorder.encoders import LIST_ARGS, PROBE_ARGS, NvencProbe, encoder_listed

LISTING = (
    "Encoders:\n"
    " V..... = Video\n"
    " ------\n"
    " V....D libx264              libx264 H.264 / AVC (codec h264)\n"
    " V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)\n"
)


class FakeRunner:
    def __init__(self, listing: str = LISTING, probe_code: int = 0, raise_on: str | None = None,
                 exc: BaseException | None = None) -> None:
        self.calls: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.listing = listing
        self.probe_code = probe_code
        self.raise_on = raise_on
        self.exc = exc

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        self.kwargs.append(dict(kwargs))
        step = "list" if argv[1:] == LIST_ARGS else "probe"
        if self.raise_on == step and self.exc is not None:
            raise self.exc
        if step == "list":
            return subprocess.CompletedProcess(argv, 0, stdout=self.listing, stderr="")
        return subprocess.CompletedProcess(argv, self.probe_code, stdout=b"", stderr=b"")


class EncoderTests(unittest.TestCase):
    def test_encoder_listed(self) -> None:
        self.assertTrue(encoder_listed(" V....D h264_nvenc           NVIDIA NVENC H.264", "h264_nvenc"))
        self.assertFalse(encoder_listed(" A..... h264_nvenc", "h264_nvenc"))
        self.assertFalse(encoder_listed(" V....D h264_nvenc_x", "h264_nvenc"))
        self.assertFalse(encoder_listed("", "h264_nvenc"))
        self.assertTrue(encoder_listed("x\r\n V....D h264_nvenc y\r\n", "h264_nvenc"))

    def test_probe_two_steps_and_cache(self) -> None:
        runner = FakeRunner()
        probe = NvencProbe(runner)
        self.assertTrue(probe.usable("/usr/bin/ffmpeg"))
        self.assertEqual(runner.calls, [["/usr/bin/ffmpeg"] + LIST_ARGS, ["/usr/bin/ffmpeg"] + PROBE_ARGS])
        self.assertEqual(runner.kwargs[0], {"capture_output": True, "text": True, "timeout": 5})
        self.assertEqual(runner.kwargs[1], {"capture_output": True, "timeout": 15})
        # Cached for the same path.
        self.assertTrue(probe.usable("/usr/bin/ffmpeg"))
        self.assertEqual(len(runner.calls), 2)
        # A new path probes again.
        self.assertTrue(probe.usable("/opt/ffmpeg"))
        self.assertEqual(len(runner.calls), 4)

    def test_not_listed_skips_step_2(self) -> None:
        runner = FakeRunner(listing=" V....D libx264 x\n")
        probe = NvencProbe(runner)
        self.assertFalse(probe.usable("ffmpeg"))
        self.assertEqual(len(runner.calls), 1)
        self.assertFalse(probe.usable("ffmpeg"))
        self.assertEqual(len(runner.calls), 1)

    def test_probe_exit_code_not_zero(self) -> None:
        probe = NvencProbe(FakeRunner(probe_code=1))
        self.assertFalse(probe.usable("ffmpeg"))

    def test_mark_unusable(self) -> None:
        runner = FakeRunner()
        probe = NvencProbe(runner)
        self.assertTrue(probe.usable("ffmpeg"))
        probe.mark_unusable("ffmpeg")
        self.assertFalse(probe.usable("ffmpeg"))
        self.assertEqual(len(runner.calls), 2)
        # Before any probe: no probe runs.
        other = NvencProbe(runner)
        other.mark_unusable("ffmpeg")
        self.assertFalse(other.usable("ffmpeg"))
        self.assertEqual(len(runner.calls), 2)

    def test_mark_unusable_during_probe_wins(self) -> None:
        probe_holder: list[NvencProbe] = []

        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if argv[1:] == PROBE_ARGS:
                probe_holder[0].mark_unusable("ffmpeg")
                return subprocess.CompletedProcess(argv, 0)
            return subprocess.CompletedProcess(argv, 0, stdout=LISTING, stderr="")

        probe = NvencProbe(runner)
        probe_holder.append(probe)
        self.assertFalse(probe.usable("ffmpeg"))

    def test_timeout_is_false(self) -> None:
        exc = subprocess.TimeoutExpired(["ffmpeg"], 15)
        self.assertFalse(NvencProbe(FakeRunner(raise_on="probe", exc=exc)).usable("ffmpeg"))
        self.assertFalse(NvencProbe(FakeRunner(raise_on="list", exc=exc)).usable("ffmpeg"))
        missing = FileNotFoundError("no ffmpeg")
        self.assertFalse(NvencProbe(FakeRunner(raise_on="list", exc=missing)).usable("ffmpeg"))

    def test_warm_up_runs_on_named_daemon_thread(self) -> None:
        seen: list[tuple[str, bool]] = []
        done = threading.Event()

        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            thread = threading.current_thread()
            seen.append((thread.name, thread.daemon))
            if argv[1:] == PROBE_ARGS:
                done.set()
                return subprocess.CompletedProcess(argv, 0)
            return subprocess.CompletedProcess(argv, 0, stdout=LISTING, stderr="")

        probe = NvencProbe(runner)
        probe.warm_up("ffmpeg")
        self.assertTrue(done.wait(5))
        self.assertTrue(probe.usable("ffmpeg"))
        self.assertEqual(seen[0], ("nvenc-probe", True))
        self.assertEqual(len(seen), 2)


if __name__ == "__main__":
    unittest.main()

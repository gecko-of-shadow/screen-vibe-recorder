"""GStreamer stream for the Wayland path (DESIGN.md 11.2).

pipewiresrc gives BGRx frames. Each frame goes to a FramePump. The pump writes
the crop to FFmpeg on its own clock (wayland_pump.py).

GUI module: it needs gi and Gst. It imports gi only inside functions, so the
module itself imports on any OS.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .geometry import Rect
from .wayland_pump import FramePump, crop_rows, frame_stride, pipeline_description

__all__ = ["GstFrame", "GstStream", "TEXT_NEED_GST", "TEXT_BAD_FRAME", "TEXT_SIZE_CHANGED", "TEXT_CAST_ENDED"]

TEXT_NEED_GST = (
    "Wayland capture needs GStreamer PipeWire support. Install gir1.2-gstreamer-1.0, "
    "gstreamer1.0-plugins-base and gstreamer1.0-pipewire. "
)
TEXT_BAD_FRAME = "Bad frame from the screen cast."
TEXT_SIZE_CHANGED = "The shared screen changed size, so the recording stopped."
TEXT_CAST_ENDED = "The screen cast ended, so the recording stopped."
TEXT_NO_SINK = "Could not build the screen cast pipeline."
TEXT_NOT_PLAYING = "The screen cast pipeline did not start."

_gst_module: Any = None
_glib_module: Any = None


def _gst() -> Any:
    """Import Gst once. Raises ImportError or ValueError when it is missing."""
    global _gst_module
    if _gst_module is None:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        _gst_module = Gst
    return _gst_module


def _glib() -> Any:
    global _glib_module
    if _glib_module is None:
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        _glib_module = GLib
    return _glib_module


def caps_size(sample: Any) -> tuple[int, int] | None:
    """Width and height from the caps of a sample, or None."""
    caps = sample.get_caps()
    if caps is None or caps.get_size() < 1:
        return None
    structure = caps.get_structure(0)
    try:
        width = int(structure.get_value("width"))
        height = int(structure.get_value("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


class GstFrame:
    """One frame from appsink. Implements wayland_pump.Frame."""

    def __init__(self, sample: Any, seq: int, stride: int) -> None:
        size = caps_size(sample)
        if size is None:
            raise ValueError(TEXT_BAD_FRAME)
        self.width, self.height = size
        self.seq = seq
        self.stride = stride
        self._sample = sample
        self._lock = threading.Lock()
        self._cache_rect: Rect | None = None
        self._cache: bytes | None = None

    def crop(self, rect: Rect) -> bytes:
        # A still screen writes the same frame many times: keep the last crop.
        with self._lock:
            if self._cache is not None and self._cache_rect == rect:
                return self._cache
            buffer = self._sample.get_buffer()
            data = buffer.extract_dup(0, buffer.get_size())
            out = crop_rows(data, self.stride, rect)
            self._cache_rect = rect
            self._cache = out
            return out


class GstStream:
    """A GStreamer pipeline that feeds a FramePump.

    on_error is always called on the GLib main thread: errors from the streaming
    thread go through GLib.idle_add, and bus errors come from the bus watch on the
    main loop. Each stream reports one error at most.
    """

    def __init__(self, source: str, pump: FramePump, on_error: Callable[[str], None]) -> None:
        self.source = source
        self.pump = pump
        self.on_error = on_error
        self._pipeline: Any = None
        self._sink: Any = None
        self._bus: Any = None
        self._handlers: list[tuple[Any, int]] = []
        self._seq = 0
        self._size: tuple[int, int] | None = None
        self._lock = threading.Lock()
        self._error_sent = False
        self._stopped = False

    @property
    def size(self) -> tuple[int, int] | None:
        """Frame size of the stream (stream px), after the first frame."""
        return self._size

    def start(self) -> str | None:
        try:
            Gst = _gst()
            _glib()  # import GLib here, not first on the streaming thread
        except (ImportError, ValueError) as exc:
            return TEXT_NEED_GST + str(exc)
        try:
            Gst.init(None)
            pipeline = Gst.parse_launch(pipeline_description(self.source))
        except Exception as exc:  # noqa: BLE001 - GLib.Error from the parser
            return str(exc) or TEXT_NO_SINK
        sink = pipeline.get_by_name("sink")
        if sink is None:
            pipeline.set_state(Gst.State.NULL)
            return TEXT_NO_SINK
        self._pipeline = pipeline
        self._sink = sink
        self._handlers.append((sink, sink.connect("new-sample", self._on_sample)))
        bus = pipeline.get_bus()
        if bus is not None:
            bus.add_signal_watch()
            self._bus = bus
            self._handlers.append((bus, bus.connect("message::error", self._on_bus_error)))
            # A live source can end with EOS and no error (for example when the node goes away).
            self._handlers.append((bus, bus.connect("message::eos", self._on_bus_eos)))
        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            self.stop()
            return TEXT_NOT_PLAYING
        return None

    def stop(self) -> None:
        """Main thread. Set the pipeline to NULL. Safe to call more than once."""
        self._stopped = True
        pipeline = self._pipeline
        self._pipeline = None
        for obj, handler_id in self._handlers:
            try:
                obj.disconnect(handler_id)
            except Exception:  # noqa: BLE001
                pass
        self._handlers = []
        if self._bus is not None:
            try:
                self._bus.remove_signal_watch()
            except Exception:  # noqa: BLE001
                pass
            self._bus = None
        self._sink = None
        if pipeline is not None:
            try:
                pipeline.set_state(_gst().State.NULL)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ callbacks

    def _on_sample(self, sink: Any) -> Any:
        """Streaming thread. Never blocks: pull the sample and give it to the pump."""
        Gst = _gst()
        sample = sink.emit("pull-sample")
        if sample is None or self._stopped:
            return Gst.FlowReturn.OK
        buffer = sample.get_buffer()
        size = caps_size(sample)
        if buffer is None or size is None:
            self._error_from_thread(TEXT_BAD_FRAME)
            return Gst.FlowReturn.OK
        width, height = size
        with self._lock:
            if self._size is None:
                self._size = size  # the first frame sets the size of the stream
            changed = self._size != size
        if changed:
            self._error_from_thread(TEXT_SIZE_CHANGED)
            return Gst.FlowReturn.OK
        stride = frame_stride(buffer.get_size(), width, height)
        if stride is None:
            self._error_from_thread(TEXT_BAD_FRAME)
            return Gst.FlowReturn.OK
        with self._lock:
            self._seq += 1
            seq = self._seq
        self.pump.offer(GstFrame(sample, seq, stride))
        return Gst.FlowReturn.OK

    def _on_bus_error(self, _bus: Any, message: Any) -> None:
        """Main thread (bus signal watch)."""
        try:
            err, _debug = message.parse_error()
            text = str(err.message if hasattr(err, "message") else err)
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
        self._send_error(text or "GStreamer error.")

    def _on_bus_eos(self, _bus: Any, _message: Any) -> None:
        """Main thread (bus signal watch). No new frame comes after EOS."""
        self._send_error(TEXT_CAST_ENDED)

    def _error_from_thread(self, text: str) -> None:
        with self._lock:
            if self._error_sent:
                return
            self._error_sent = True

        def deliver() -> bool:
            if self.on_error is not None:
                self.on_error(text)
            return False

        try:
            _glib().idle_add(deliver)
        except Exception:  # noqa: BLE001 - no GLib: nothing can show the error
            pass

    def _send_error(self, text: str) -> None:
        with self._lock:
            if self._error_sent:
                return
            self._error_sent = True
        if self.on_error is not None:
            self.on_error(text)

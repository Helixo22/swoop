"""Animated speed widgets: a scrolling area graph and a counting speed label.

New samples slide in smoothly and the vertical scale eases towards the new
maximum; libadwaita skips the animations when the system asks to reduce motion.
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Callable

import cairo
from gi.repository import Adw, Gtk

from swoop import text

HISTORY = 60  # samples, one per refresh
SLIDE_MS = 900
VIOLET = (0x7C / 255, 0x6C / 255, 0xF0 / 255)
INDIGO = (0x3A / 255, 0x52 / 255, 0xD6 / 255)


def _animation(
    widget: Gtk.Widget, duration: int, step: Callable[[float], None]
) -> Adw.TimedAnimation:
    target = Adw.CallbackAnimationTarget.new(step)
    animation = Adw.TimedAnimation.new(widget, 0, 1, duration, target)
    animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
    return animation


class SpeedGraph(Gtk.DrawingArea):
    """Area graph of the last minute of speed samples, scrolling to the left."""

    def __init__(self, *, height: int = 72, line_width: float = 2.5, width: int = 0) -> None:
        # width 0: expand horizontally; otherwise a fixed-size sparkline
        super().__init__(content_height=height, content_width=width, hexpand=not width)
        self._samples: deque[int] = deque(maxlen=HISTORY + 1)  # one extra slides out
        self._line_width = line_width
        self._shift = 0.0  # 1 right after a new sample, eases to 0
        self._scale = 1.0
        self._scale_from = self._scale_to = 1.0
        self._animation = _animation(self, SLIDE_MS, self._step)
        self.set_draw_func(self._draw)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Download speed over the last minute"]
        )

    def push(self, speed: int) -> None:
        self._samples.append(speed)
        self._scale_from, self._scale_to = self._scale, max(max(self._samples), 1)
        self._animation.reset()
        self._animation.play()

    def _step(self, value: float) -> None:
        self._shift = 1 - value
        self._scale = self._scale_from + (self._scale_to - self._scale_from) * value
        self.queue_draw()

    def _points(self, width: int, height: int) -> list[tuple[float, float]]:
        """Newest sample at the right edge; while sliding, everything is shifted right."""
        step = width / (HISTORY - 1)
        top = self._line_width + 2
        usable = height - top - self._line_width
        last = len(self._samples) - 1
        return [
            (
                width - (last - index - self._shift) * step,
                top + usable * (1 - min(sample / self._scale, 1)),
            )
            for index, sample in enumerate(self._samples)
        ]

    def _draw(
        self, _: Gtk.DrawingArea, context: cairo.Context[cairo.Surface], width: int, height: int
    ) -> None:
        points = self._points(width, height)
        if len(points) < 2:
            return
        _smooth_path(context, points)
        context.line_to(points[-1][0], height)
        context.line_to(points[0][0], height)
        context.close_path()
        fill = cairo.LinearGradient(0, 0, 0, height)
        fill.add_color_stop_rgba(0, *VIOLET, 0.35)
        fill.add_color_stop_rgba(1, *INDIGO, 0.0)
        context.set_source(fill)
        context.fill()

        _smooth_path(context, points)
        line = cairo.LinearGradient(0, 0, width, 0)
        line.add_color_stop_rgb(0, *VIOLET)
        line.add_color_stop_rgb(1, *INDIGO)
        context.set_source(line)
        context.set_line_width(self._line_width)
        context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.set_line_join(cairo.LINE_JOIN_ROUND)
        context.stroke()


def _smooth_path(context: cairo.Context[cairo.Surface], points: list[tuple[float, float]]) -> None:
    """Curve through the points using midpoints as Bézier control anchors."""
    context.move_to(*points[0])
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        middle_x = (x0 + x1) / 2
        context.curve_to(middle_x, y0, middle_x, y1, x1, y1)


class SpeedLabel(Gtk.Label):
    """Shows a speed that counts smoothly towards each new value."""

    def __init__(self) -> None:
        super().__init__(label=text.speed(0), xalign=0)
        self._shown = 0.0
        self._start = self._target = 0.0
        self._animation = _animation(self, SLIDE_MS, self._step)

    def set_speed(self, speed: int) -> None:
        self._start, self._target = self._shown, float(speed)
        self._animation.reset()
        self._animation.play()

    def _step(self, value: float) -> None:
        self._shown = self._start + (self._target - self._start) * value
        self.set_label(text.speed(round(self._shown)))

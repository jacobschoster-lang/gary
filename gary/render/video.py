"""Render an animated stick-figure video (MP4) from a content plan.

Each video-plan segment becomes a scene: a titled backdrop, a finance prop that
matches the beat, an animated stick figure gesturing, and a wrapped caption of
the narration. Frames are drawn with Pillow and encoded to H.264 via the system
``ffmpeg`` binary.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from gary.render.stickfigure import (
    GESTURES,
    draw_arrow,
    draw_chart,
    draw_coin,
    draw_stick_figure,
)

BG_TOP = (11, 15, 20)
ACCENT = (37, 99, 235)
WHITE = (245, 245, 245)
MUTED = (139, 152, 165)

# Map each transcript beat to a gesture + prop so the figure "acts out" the story.
_SCENE_STYLE = {
    "Hook": ("wave", "coin"),
    "The Data": ("present", "chart"),
    "Analysis": ("point_up", "arrow_up"),
    "Call To Action": ("wave", "arrow_up"),
}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_prop(draw: ImageDraw.ImageDraw, prop: str, w: int, h: int) -> None:
    px = w * 0.72
    py = h * 0.62
    if prop == "coin":
        draw_coin(draw, px, py - 40, r=40)
    elif prop == "chart":
        draw_chart(draw, px - 60, py + 40, scale=1.4)
    elif prop == "arrow_up":
        draw_arrow(draw, px, py, up=True, scale=1.3)
    elif prop == "arrow_down":
        draw_arrow(draw, px, py, up=False, scale=1.3)


def _render_frame(
    heading: str,
    caption: str,
    gesture: str,
    prop: str,
    phase: float,
    width: int,
    height: int,
    title_font: ImageFont.ImageFont,
    body_font: ImageFont.ImageFont,
    head_font: ImageFont.ImageFont,
) -> Image.Image:
    img = Image.new("RGB", (width, height), BG_TOP)
    draw = ImageDraw.Draw(img)

    # Accent header bar + scene heading
    draw.rectangle([0, 0, width, 70], fill=(17, 24, 39))
    draw.rectangle([0, 0, 12, height], fill=ACCENT)
    draw.text((40, 20), "gary finance", font=title_font, fill=ACCENT)
    draw.text((width - 360, 22), heading.upper(), font=head_font, fill=MUTED)

    # Ground line
    ground = int(height * 0.78)
    draw.line([(20, ground), (width - 20, ground)], fill=(31, 42, 55), width=3)

    # Prop + animated stick figure
    _draw_prop(draw, prop, width, height)
    pose = GESTURES.get(gesture, GESTURES["idle"])(phase)
    draw_stick_figure(draw, width * 0.32, ground, scale=1.9, pose=pose)

    # Caption box
    box_top = ground + 18
    draw.rectangle([30, box_top, width - 30, height - 20], fill=(17, 24, 39))
    lines = textwrap.wrap(caption, width=64)[:3]
    ty = box_top + 14
    for line in lines:
        draw.text((50, ty), line, font=body_font, fill=WHITE)
        ty += 34
    return img


def render_story(
    plan: dict[str, Any],
    out_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 12,
    seconds_per_scene: float = 4.0,
) -> str:
    """Render ``plan`` (a pipeline result) to an MP4 at ``out_path``."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg binary not found; install ffmpeg to render video")

    segments = plan["video_long"]["segments"]
    topic = plan["topic"]
    title_font = _font(30)
    head_font = _font(24)
    body_font = _font(26)
    big_font = _font(52)

    frames_per_scene = max(1, int(fps * seconds_per_scene))
    out_path = str(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        idx = 0

        # Title card
        for f in range(frames_per_scene):
            img = Image.new("RGB", (width, height), BG_TOP)
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, 12, height], fill=ACCENT)
            draw.text((60, height * 0.30), "STICKFIGURE FINANCE", font=big_font, fill=ACCENT)
            draw.text((60, height * 0.30 + 70), topic, font=title_font, fill=WHITE)
            phase = f / frames_per_scene
            draw_stick_figure(
                draw, width * 0.5, int(height * 0.86), scale=2.0,
                pose=GESTURES["wave"](phase),
            )
            img.save(Path(tmp) / f"frame_{idx:05d}.png")
            idx += 1

        # Story scenes
        for seg in segments:
            gesture, prop = _SCENE_STYLE.get(seg["heading"], ("idle", "coin"))
            for f in range(frames_per_scene):
                phase = f / frames_per_scene
                img = _render_frame(
                    seg["heading"], seg["script"], gesture, prop, phase,
                    width, height, title_font, body_font, head_font,
                )
                img.save(Path(tmp) / f"frame_{idx:05d}.png")
                idx += 1

        cmd = [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(Path(tmp) / "frame_%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            out_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    return out_path

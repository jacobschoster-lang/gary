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
    draw.text((40, 20), "Stickfigure Finance", font=title_font, fill=ACCENT)
    draw.text((width - 360, 22), heading.upper(), font=head_font, fill=MUTED)

    # Ground line
    ground = int(height * 0.78)
    draw.line([(20, ground), (width - 20, ground)], fill=(31, 42, 55), width=3)

    # Prop + animated stick figure
    _draw_prop(draw, prop, width, height)
    pose = GESTURES.get(gesture, GESTURES["idle"])(phase)
    draw_stick_figure(draw, width * 0.32, ground, scale=1.9, pose=pose)

    # Caption box
    box_top = ground + 12
    draw.rectangle([30, box_top, width - 30, height - 12], fill=(17, 24, 39))
    lines = textwrap.wrap(caption, width=76)[:4]
    ty = box_top + 12
    for line in lines:
        draw.text((50, ty), line, font=body_font, fill=WHITE)
        ty += 30
    return img


def _audio_duration(path: str) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            check=True, capture_output=True, text=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def _scene_audio(tmp: Path, index: int, narration_mp3: str | None, seconds: float) -> Path:
    """Return a WAV of exactly ``seconds`` (narration padded with silence, or silence)."""
    out = tmp / f"audio_{index:03d}.wav"
    if narration_mp3:
        cmd = ["ffmpeg", "-y", "-i", narration_mp3, "-af", "apad",
               "-t", f"{seconds:.3f}", "-ar", "44100", "-ac", "1", str(out)]
    else:
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
               "-t", f"{seconds:.3f}", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def render_story(
    plan: dict[str, Any],
    out_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 12,
    seconds_per_scene: float = 4.0,
    voiceover: bool = True,
    max_scene_seconds: float = 18.0,
) -> str:
    """Render ``plan`` (a pipeline result) to an MP4 at ``out_path``.

    When ``voiceover`` is set, each scene is narrated (gTTS) and its on-screen
    duration matches the narration length; audio is muxed into the final MP4.
    Falls back to silent, fixed-length scenes when TTS/network is unavailable.
    """
    from gary.render.tts import synthesize

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg binary not found; install ffmpeg to render video")

    topic = plan["topic"]
    title_font = _font(30)
    head_font = _font(24)
    body_font = _font(24)
    big_font = _font(52)
    out_path = str(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # Each scene = (heading, caption, gesture, prop, narration_text)
    scenes: list[tuple[str, str, str, str, str]] = [
        ("__title__", topic, "wave", "coin",
         f"Welcome to Stickfigure Finance. Today, {topic}."),
    ]
    for seg in plan["video_long"]["segments"]:
        gesture, prop = _SCENE_STYLE.get(seg["heading"], ("idle", "coin"))
        scenes.append((seg["heading"], seg["script"], gesture, prop, seg["script"]))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        idx = 0
        scene_audios: list[Path] = []

        for si, (heading, caption, gesture, prop, narration) in enumerate(scenes):
            narration_mp3: str | None = None
            duration = seconds_per_scene
            if voiceover:
                mp3 = tmp / f"narr_{si:03d}.mp3"
                if synthesize(narration, str(mp3)):
                    narration_mp3 = str(mp3)
                    dur = _audio_duration(narration_mp3)
                    if dur:
                        duration = min(max_scene_seconds, max(2.0, dur + 0.4))

            frames = max(1, round(fps * duration))
            for f in range(frames):
                phase = f / frames
                if heading == "__title__":
                    img = Image.new("RGB", (width, height), BG_TOP)
                    draw = ImageDraw.Draw(img)
                    draw.rectangle([0, 0, 12, height], fill=ACCENT)
                    draw.text((60, height * 0.30), "STICKFIGURE FINANCE",
                              font=big_font, fill=ACCENT)
                    draw.text((60, height * 0.30 + 70), topic, font=title_font, fill=WHITE)
                    draw_stick_figure(draw, width * 0.5, int(height * 0.86), scale=2.0,
                                      pose=GESTURES["wave"](phase))
                else:
                    img = _render_frame(heading, caption, gesture, prop, phase,
                                        width, height, title_font, body_font, head_font)
                img.save(tmp / f"frame_{idx:05d}.png")
                idx += 1

            scene_audios.append(_scene_audio(tmp, si, narration_mp3, frames / fps))

        silent = tmp / "silent.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps),
             "-i", str(tmp / "frame_%05d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(silent)],
            check=True, capture_output=True,
        )

        # Concatenate per-scene audio and mux with the video.
        listfile = tmp / "audio_list.txt"
        listfile.write_text("".join(f"file '{p}'\n" for p in scene_audios), encoding="utf-8")
        full_audio = tmp / "full.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile), str(full_audio)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(silent), "-i", str(full_audio),
             "-c:v", "copy", "-c:a", "aac", "-shortest", out_path],
            check=True, capture_output=True,
        )

    return out_path

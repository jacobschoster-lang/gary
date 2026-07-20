import shutil

import pytest
from PIL import Image, ImageDraw

from gary.pipeline import ContentPipeline
from gary.render import render_story
from gary.render.stickfigure import GESTURES, Pose, draw_stick_figure

ffmpeg_missing = shutil.which("ffmpeg") is None


def test_draw_stick_figure_marks_pixels():
    img = Image.new("RGB", (200, 240), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_stick_figure(draw, 100, 220, scale=1.5, pose=Pose())
    # Some non-black pixels should have been drawn.
    assert img.getbbox() is not None


def test_all_gestures_return_pose():
    for name, fn in GESTURES.items():
        pose = fn(0.5)
        assert isinstance(pose, Pose), name


def test_split_sentences():
    from gary.render.video import _split_sentences

    out = _split_sentences("First sentence. Second one! Third? ")
    assert out == ["First sentence.", "Second one!", "Third?"]
    assert _split_sentences("no punctuation here") == ["no punctuation here"]


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not installed")
@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not installed")
def test_render_story_produces_mp4(tmp_path):
    plan = ContentPipeline(use_live=False).run_daily(topic="Bitcoin ETF inflows")
    out = tmp_path / "story.mp4"
    # voiceover is stubbed off by the offline fixture -> silent, still valid MP4.
    render_story(plan, out_path=str(out), fps=6, seconds_per_scene=1.0)
    assert out.exists()
    assert out.stat().st_size > 5000  # a real, non-trivial video file


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not installed")
def test_render_story_short_plan(tmp_path):
    plan = ContentPipeline(use_live=False).run_daily(topic="Bitcoin ETF inflows")
    out = tmp_path / "short.mp4"
    render_story(
        plan,
        out_path=str(out),
        video_key="video_short",
        fps=6,
        seconds_per_scene=1.0,
        voiceover=False,
    )
    assert out.exists()
    assert out.stat().st_size > 0

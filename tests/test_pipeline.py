import pytest

from gary.agents import Publisher, ThumbnailAgent, TranscriptAgent, TrendsAgent, VideoAgent
from gary.pipeline import ContentPipeline


def test_youtube_topics_ranked():
    topics = TrendsAgent().youtube_topics(limit=3)
    assert len(topics) == 3
    velocities = [t.velocity for t in topics]
    assert velocities == sorted(velocities, reverse=True)


def test_video_agent_long_and_short():
    transcript = TranscriptAgent().generate("Fed rate decision")
    va = VideoAgent()
    long_plan = va.build(transcript, "long")
    short_plan = va.build(transcript, "short")
    assert long_plan.kind == "long"
    assert long_plan.total_seconds > 0
    # Shorts keep fewer segments than the full long-form plan.
    assert len(short_plan.segments) < len(long_plan.segments)


def test_video_agent_rejects_bad_kind():
    transcript = TranscriptAgent().generate("x")
    with pytest.raises(ValueError):
        VideoAgent().build(transcript, "reel")  # type: ignore[arg-type]


def test_thumbnail_design_is_deterministic_and_renders_svg():
    agent = ThumbnailAgent()
    a = agent.design("Bitcoin ETF inflows")
    b = agent.design("Bitcoin ETF inflows")
    assert a == b
    svg = agent.render_svg(a)
    assert svg.startswith("<svg")
    assert a.headline in svg or a.headline.split()[0] in svg


def test_thumbnail_save_png(tmp_path):
    agent = ThumbnailAgent()
    spec = agent.design("Bitcoin ETF inflows")
    out = agent.save_png(spec, tmp_path / "thumb.png")
    assert (tmp_path / "thumb.png").exists()
    assert out.endswith("thumb.png")


def test_publisher_upload_track_and_comments():
    pub = Publisher()
    video = pub.upload("My Finance Video", kind="long")
    assert video.url.endswith(video.video_id)
    metrics = pub.track(video.video_id)
    assert metrics["views"] > 0
    assert metrics["source"] == "sample"
    replies = pub.manage_comments(video.video_id, ["nice video", "thanks!"], top_n=10)
    assert len(replies) == 2
    assert all("reply" in r for r in replies)


def test_publisher_unknown_video():
    with pytest.raises(KeyError):
        Publisher().track("does-not-exist")


def test_pipeline_run_daily_end_to_end():
    result = ContentPipeline().run_daily(topic="Bitcoin ETF inflows")
    assert result["topic"] == "Bitcoin ETF inflows"
    for key in ("transcript", "video_long", "video_short", "thumbnail", "published", "metrics"):
        assert key in result
    assert result["published"]["url"].startswith("https://youtu.be/")


def test_pipeline_auto_picks_topic():
    result = ContentPipeline().run_daily(market="crypto")
    assert result["topic"]


def test_pipeline_auto_picks_quantum_topic():
    result = ContentPipeline().run_daily(market="quantum")
    assert result["topic"]

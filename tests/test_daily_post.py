from datetime import datetime, timezone

from gary.integrations.youtube import YouTubeUploader
from gary.jobs.daily_post import build_description, build_tags, run
from gary.jobs.schedule import should_run_now


def test_schedule_dst_summer_edt():
    # 12:00 UTC == 08:00 EDT in July -> should run.
    assert should_run_now(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)) is True
    # 13:00 UTC == 09:00 EDT in July -> should not run.
    assert should_run_now(datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc)) is False


def test_schedule_dst_winter_est():
    # 13:00 UTC == 08:00 EST in January -> should run.
    assert should_run_now(datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)) is True
    # 12:00 UTC == 07:00 EST in January -> should not run.
    assert should_run_now(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)) is False


def test_uploader_from_env_absent(monkeypatch):
    for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert YouTubeUploader.from_env() is None


def test_uploader_from_env_present():
    env = {
        "YOUTUBE_CLIENT_ID": "cid",
        "YOUTUBE_CLIENT_SECRET": "secret",
        "YOUTUBE_REFRESH_TOKEN": "refresh",
        "YOUTUBE_PRIVACY": "unlisted",
    }
    up = YouTubeUploader.from_env(env)
    assert up is not None
    assert up.privacy == "unlisted"


def test_daily_post_dry_run_no_credentials(tmp_path, monkeypatch):
    for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    result = run(topic="Bitcoin ETF inflows", out_dir=str(tmp_path), force=True)
    assert result["uploaded"] is False
    assert result["dry_run"] is True
    assert "credentials not configured" in result["reason"]
    assert result["channel"] == "@StickfigureFinance-r8m"
    assert "manifest" in result


def test_daily_post_skips_when_not_scheduled(tmp_path):
    off_hour = datetime(2026, 7, 1, 3, 0, tzinfo=timezone.utc)  # 23:00 ET prev day
    result = run(topic="x", out_dir=str(tmp_path), now_utc=off_hour)
    assert result["scheduled_ok"] is False
    assert result["uploaded"] is False


def test_description_and_tags():
    from gary.pipeline import ContentPipeline

    plan = ContentPipeline().run_daily(topic="Solana DeFi surge")
    desc = build_description(plan)
    assert "not financial advice" in desc
    tags = build_tags(plan)
    assert "finance" in tags

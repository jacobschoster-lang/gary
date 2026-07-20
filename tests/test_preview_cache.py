from gary.render.preview_cache import _cache_path, get_or_render


def test_preview_cache_reuses_existing(tmp_path, monkeypatch):
    monkeypatch.setattr("gary.render.preview_cache._CACHE_ROOT", tmp_path)
    calls = {"n": 0}

    def plan_factory(topic: str):
        return {"topic": topic, "video_long": {"segments": []}}

    def render_fn(plan, out_path: str, **kwargs):
        calls["n"] += 1
        with open(out_path, "wb") as f:
            f.write(b"mp4")

    path1 = get_or_render("Bitcoin", False, plan_factory, render_fn)
    path2 = get_or_render("Bitcoin", False, plan_factory, render_fn)
    assert path1 == path2
    assert calls["n"] == 1


def test_cache_path_differs_by_voice(tmp_path, monkeypatch):
    monkeypatch.setattr("gary.render.preview_cache._CACHE_ROOT", tmp_path)
    assert _cache_path("topic", False) != _cache_path("topic", True)

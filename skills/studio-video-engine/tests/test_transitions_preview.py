"""T-E42 follow-up: ``boundaries preview`` (gallery of short windows) and the proxy compositor."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from engine.core.errors import Refused  # noqa: E402
from engine.editorial import boundaries_preview as bp  # noqa: E402
from engine.editorial import boundaries_preview_fx as fx  # noqa: E402
from engine.editorial import boundaries_suggest as bs  # noqa: E402
from engine.editorial import presets  # noqa: E402
from engine.editorial.boundaries_suggest_measure import find_ffmpeg  # noqa: E402
from transitions_fixtures import GRAD_X, GRAD_Y, build, declared, needs_ffmpeg  # noqa: E402

A_COLOUR, B_COLOUR = (200, 40, 40), (40, 40, 200)


def solid(colour: tuple, h: int = 18, w: int = 32):
    frame = np.empty((h, w, 3), np.uint8)
    frame[...] = colour
    return lambda t: frame


def render(name: str, t: int, frames: int | None = None, direction: int = 1, params: dict | None = None):
    preset = presets.get(name)
    n = frames if frames is not None else presets.default_frames(preset)
    return fx.compose(preset, n, direction if preset.direction == "required" else 0,
                      presets.resolve_params(preset, params), t, solid(A_COLOUR), solid(B_COLOUR))


# ---- the proxy compositor ------------------------------------------------------------------------------------------
SUPPORTED = [n for n, p in presets.presets().items() if p.ready and fx.supported(p)]


@pytest.mark.parametrize("name", SUPPORTED)
def test_every_supported_preset_is_pure_outgoing_before_and_pure_incoming_after_its_window(name: str) -> None:
    out_before, out_after = render(name, -60), render(name, 60)
    assert out_before.shape == (18, 32, 3) and out_before.dtype == np.uint8
    assert (out_before == A_COLOUR).all() and (out_after == B_COLOUR).all()


@pytest.mark.parametrize("name", SUPPORTED)
def test_every_supported_preset_renders_each_frame_of_its_window_with_finite_8_bit_pixels(name: str) -> None:
    preset = presets.get(name)
    start, end = presets.window(preset, 0, presets.default_frames(preset), presets.resolve_params(preset, None))
    for t in range(start - 1, end + 1):
        assert render(name, t).shape == (18, 32, 3)


def test_the_cloud_the_bubble_and_the_graphic_presets_are_not_faked() -> None:
    for name in ("cloud", "bubble", "iris", "card_slide", "plate_in"):
        with pytest.raises(fx.ProxyUnavailable, match="kit renderer"):
            render(name, 0)
    assert not fx.supported(presets.get("cloud"))


def test_a_dip_is_one_shot_per_frame_with_exactly_one_pure_colour_frame_at_the_schedule_peak() -> None:
    preset = presets.get("dip_white")
    rows = {row["t"]: row for row in preset.schedule}
    peak = next(t for t, row in rows.items() if row["white"] == 1.0)
    flat = render("dip_white", peak)
    assert (flat == (255, 248, 236)).all()                 # #FFF8EC, the catalog colour
    pure = [t for t in rows if (render("dip_white", t) == (255, 248, 236)).all()]
    assert pure == [peak]
    mid = render("dip_white", -1)                          # outgoing brightening: red-ish, never blue (no second shot)
    assert mid[0, 0, 0] > mid[0, 0, 2] and not (mid == A_COLOUR).all()
    assert render("dip_white", peak + 1)[0, 0, 2] > render("dip_white", peak + 1)[0, 0, 0]   # incoming emerges from white
    black = fx.compose(presets.get("dip_black"), 8, 0, {}, -1, solid(A_COLOUR), solid(B_COLOUR))
    assert black[0, 0, 0] < A_COLOUR[0]


def test_a_push_in_starts_zoomed_and_ends_on_the_unscaled_incoming_frame() -> None:
    ramp = np.tile(np.arange(64, dtype=np.uint8)[None, :, None], (36, 1, 3))
    preset = presets.get("cut_push")
    first = fx.compose(preset, 12, 0, presets.resolve_params(preset, None), 0, solid(A_COLOUR), lambda t: ramp)
    last = fx.compose(preset, 12, 0, presets.resolve_params(preset, None), 11, solid(A_COLOUR), lambda t: ramp)
    assert first[18, 0, 0] > ramp[18, 0, 0] and first[18, -1, 0] < ramp[18, -1, 0]     # edges cropped: zoomed in 4%
    assert np.abs(last.astype(int) - ramp.astype(int)).max() <= 3                      # almost settled at 1.00
    assert (fx.compose(preset, 12, 0, presets.resolve_params(preset, None), 12, solid(A_COLOUR), lambda t: ramp) == ramp).all()


def test_a_whip_moves_the_outgoing_one_way_and_the_incoming_from_the_other_side() -> None:
    gradient = np.tile(np.linspace(0, 255, 64, dtype=np.uint8)[None, :, None], (8, 1, 3))
    preset = presets.get("whip")
    left = fx.compose(preset, 8, 1, {}, -1, lambda t: gradient, solid(B_COLOUR, 8, 64))
    right = fx.compose(preset, 8, -1, {}, -1, lambda t: gradient, solid(B_COLOUR, 8, 64))
    assert left.mean() != right.mean() and not (left == gradient).all()
    assert left[0, 0, 0] != gradient[0, 0, 0] or left[0, -1, 0] != gradient[0, -1, 0]


def test_mix_blur_and_scale_helpers() -> None:
    a, b = solid(A_COLOUR)(0), solid(B_COLOUR)(0)
    assert (fx.mix(a, b, 0.0) == a).all() and (fx.mix(a, b, 1.0) == b).all()
    half = fx.mix(a, b, 0.5)
    assert abs(int(half[0, 0, 0]) - 120) <= 1 and abs(int(half[0, 0, 2]) - 120) <= 1
    noise = (np.arange(18 * 32 * 3).reshape(18, 32, 3) * 37 % 256).astype(np.uint8)
    assert fx.blur(noise, 3).std() < noise.std() and (fx.blur(noise, 0) == noise).all()
    small, inside = fx.scale_xy(noise, 0.5, 0.5)
    assert inside[9, 16] and not inside[0, 0]


# ---- tokens, specs, verdicts -------------------------------------------------------------------------------------------
def test_tokens_resolve_the_users_words_and_carry_options() -> None:
    got = bp.parse_tokens("push,dip,flash,cut,whip:direction=-1,cut_push:frames=8:scale_from=1.06,dip_white:sparkles=false")
    assert [t["name"] for t in got] == ["cut_push", "dip_white", "dip_white", "cut", "whip", "cut_push", "dip_white"]
    assert got[4]["direction"] == -1 and got[5]["frames"] == 8 and got[5]["params"] == {"scale_from": 1.06}
    assert got[6]["params"] == {"sparkles": False}
    with pytest.raises(Refused, match="key=value"):
        bp.parse_tokens("whip:left")
    with pytest.raises(Refused, match="names no preset"):
        bp.parse_tokens(" , ")


def test_a_spec_is_validated_like_a_boundary_row() -> None:
    item = {"chosen": {"type": "cut_push", "frames": 12, "direction": 0}, "alternatives": []}
    assert bp.candidate_spec(item, bp.parse_tokens("cut_push:frames=8")[0])["frames"] == 8
    with pytest.raises(Refused, match="frames"):
        bp.candidate_spec(item, bp.parse_tokens("whip:frames=9")[0])         # whip: even, 4..8
    with pytest.raises(Refused, match="unknown param"):
        bp.candidate_spec(item, bp.parse_tokens("cut_push:nonsense=1")[0])
    with pytest.raises(Refused, match="unknown transition preset"):
        bp.candidate_spec(item, bp.parse_tokens("sparkle_wipe")[0])
    with pytest.raises(Refused, match="planned"):
        bp.candidate_spec(item, bp.parse_tokens("glitch")[0])


# ---- the gallery ----------------------------------------------------------------------------------------------------------
def probe_clip(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,nb_read_packets,pix_fmt", "-of", "json", str(path)],
                         capture_output=True, check=True)
    return json.loads(out.stdout)["streams"][0]


@needs_ffmpeg
def test_preview_renders_only_a_short_window_per_candidate_and_the_page_is_a_white_page(tmp_path: Path) -> None:
    config, shots = build(tmp_path / "ep", [("S01_A", 40, "cut", GRAD_X), ("S01_B", 40, "cut", GRAD_Y)], tail={"S01_A": 13})
    row = {"from_shot": "S01_A", "to_shot": "S01_B", "continuity": "mismatch", "motivation": "tree to bench"}
    ctx = bs.make_context(config, shots, declared([row]), ffmpeg=find_ffmpeg())
    item = next(it for it in bs.suggest(config, shots, declared([row]), ctx=ctx)["boundaries"] if it["kind"] == "picture")
    out = tmp_path / "gallery"
    record = bp.preview(ctx, item, bp.parse_tokens("dip,whip,push,crossfade"), out, find_ffmpeg(), shots[0], shots[1],
                        swap_hint="jjv editorial boundaries swap --episode E")
    by = {c["token"]: c for c in record["candidates"]}
    for token in ("dip", "whip", "push"):
        info = probe_clip(out / by[token]["clip"])
        assert (info["width"], info["height"], info["r_frame_rate"], info["nb_read_packets"], info["pix_fmt"]) == (
            1920, 1080, "30/1", "48", "yuv420p")                           # 24 delivery frames each side of the cut
        assert by[token]["status"] == "rendered" and by[token]["render_seconds"] > 0
        assert (out / by[token]["poster"]).is_file() and len(by[token]["sha256"]) == 64
    assert by["dip"]["verdict"]["chosen"] is True and by["dip"]["tail"]["needed"] is True
    assert by["push"]["verdict"]["allowed"] is False and "R5_new_framing_dip" in by["push"]["verdict"]["text"]
    assert by["crossfade"]["verdict"]["allowed"] is False and "both sides in one frame" in by["crossfade"]["verdict"]["text"]
    assert by["crossfade"]["status"] == "rendered"                         # still shown, labelled: compare by eye
    assert record["frame_range_from_cut"] == [-24, 24] and record["render_seconds_total"] >= record["decode_seconds"]
    page = (out / "index.html").read_text("utf-8")
    assert "prefers-color-scheme" not in page and "data-theme" not in page and "background:#FFFFFF" in page
    assert 'src="clips/dip.mp4"' in page and "boundaries swap --episode E" in page
    assert json.loads((out / "preview-record.json").read_text("utf-8"))["boundary"] == item["id"]


@needs_ffmpeg
def test_a_tail_preset_without_a_handle_gets_a_card_with_the_reason_and_no_clip(tmp_path: Path) -> None:
    config, shots = build(tmp_path / "ep", [("S01_A", 40, "cut", GRAD_X), ("S01_B", 40, "cut", GRAD_Y)])   # no native clip
    ctx = bs.make_context(config, shots, None, ffmpeg=find_ffmpeg())
    item = next(it for it in bs.suggest(config, shots, ctx=ctx)["boundaries"] if it["kind"] == "picture")
    record = bp.preview(ctx, item, bp.parse_tokens("dip,whip,cloud"), tmp_path / "g", find_ffmpeg(), shots[0], shots[1])
    by = {c["preset"]: c for c in record["candidates"]}
    assert by["dip_white"]["status"] == "not_rendered" and by["dip_white"]["clip"] is None
    assert "no GPU work is requested" in by["dip_white"]["reason"]
    assert by["whip"]["status"] == "rendered"
    assert by["cloud"]["status"] == "not_rendered" and "kit renderer" in by["cloud"]["reason"]
    assert not (tmp_path / "g" / "clips" / "dip.mp4").exists()
    assert "no clip: " in (tmp_path / "g" / "index.html").read_text("utf-8")

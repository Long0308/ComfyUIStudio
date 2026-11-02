"""M9a item b: ``qa review`` (Q5 pacing / length) compares against the episode DELIVERY CONTRACT, not the recipe literals."""

from __future__ import annotations

import argparse
import copy
import json
from types import SimpleNamespace

import pytest

from engine.core.errors import Refused
from engine.qa import review, review_cli
from engine.qa.gates import FAIL, q5_pacing
from engine.qa.review_model import build_model
from test_qa_review_q5 import check, config
from test_qa_review_support import recipe

LIMITS = {"card_min": 100, "logo_hold_min": 60}


def test_domain_floor_raises_the_q5_card_floor_so_90_frame_cards_fail() -> None:
    cfg, base = config(), recipe()
    assert check(q5_pacing.pacing(cfg, build_model(cfg, base), base, None)[0], "card_length")["ok"]   # 90 f cards pass today
    bound, overrides = copy.deepcopy(base), {}
    review.bind_contract(bound, overrides, limits=LIMITS, episode_total=None, explicit=None, declared=None)
    assert bound["q5_pacing"]["card_min_frames"] == 100 and overrides == {"q5_pacing.card_min_frames": "domain"}
    assert not check(q5_pacing.pacing(cfg, build_model(cfg, bound), bound, None)[0], "card_length")["ok"]


def test_the_episode_contract_total_is_the_default_expected_length() -> None:
    expect = review.bind_contract(recipe(), {}, limits=None, episode_total=3444, explicit=None, declared=None)
    assert expect == 3444
    cfg, rec = config(), recipe()
    checks, _ = q5_pacing.pacing(cfg, build_model(cfg, rec), rec, expect)
    assert not check(checks, "contract_frames")["ok"]        # the 540 f config is not the 3444 f contract
    assert q5_pacing.run(cfg, build_model(cfg, rec), rec, None, None, None, None, 0, expect, False)["status"] == FAIL


@pytest.mark.parametrize("explicit,declared", [(540, None), (None, 540)])
def test_a_length_that_contradicts_the_episode_contract_is_refused(explicit, declared) -> None:
    with pytest.raises(Refused, match="episode contract"):
        review.bind_contract(recipe(), {}, limits=None, episode_total=3444, explicit=explicit, declared=declared)


def test_without_an_episode_nothing_changes() -> None:
    base = recipe()
    bound = copy.deepcopy(base)
    assert review.bind_contract(bound, {}, limits=None, episode_total=None, explicit=540, declared=None) == 540
    assert bound == base


def test_run_review_refuses_before_decoding_when_the_contract_disagrees(tmp_path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with pytest.raises(Refused, match="episode contract"):
        review.run_review(config=config(), video=video, ffmpeg="ffmpeg", recipe=recipe(), recipe_sha256="0" * 64,
                          config_sha256="0" * 64, root=tmp_path, expect_frames=540, episode_total=3444, limits=LIMITS)


def test_the_review_cli_reads_the_contract_from_the_episode(tmp_path, monkeypatch) -> None:
    seen = {}
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(config()), encoding="utf-8")
    domain = {"domain_id": "d", "frame_rates": {"delivery_fps": 30},
              "delivery": {"sections": {"vocab_card": {"min": 100, "max": 150}, "logo_hold": {"min": 70, "max": 120}},
                           "end_card": {"frames_min": 60, "frames_max": 60}}}
    episode = SimpleNamespace(domain=domain, episode={"timeline": {}, "contract": {
        "main_frames": 3384, "end_card_frames": 60, "total_frames": 3444}}, episode_root=str(tmp_path))
    monkeypatch.setattr(review_cli, "resolve_episode_or_uncertain", lambda ref: episode)
    monkeypatch.setattr(review_cli, "find_ffmpeg", lambda explicit=None: "ffmpeg")
    monkeypatch.setattr(review, "run_review", lambda **kw: seen.update(kw) or {"exit_code": 0, "verdict": "PASS"})
    parser = argparse.ArgumentParser()
    review_cli.add_arguments(parser)
    args = parser.parse_args(["--config", str(cfg), "--video", str(cfg), "--episode", "x", "--json"])
    assert review_cli.run_qa_review(args) == 0
    assert seen["episode_total"] == 3444 and seen["limits"]["card_min"] == 100 and seen["limits"]["logo_hold_min"] == 70

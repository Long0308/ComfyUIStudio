"""Script ingest refuses missing domain section policy with a useful key."""

import json

import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.script.ingest import derive


def _inputs(domain_id: str) -> tuple[dict, dict, dict]:
    domain = json.loads((SKILL_ROOT / "domains" / f"{domain_id}.json").read_text(encoding="utf-8"))
    episode = {"episode_id": "n18", "film_id": "n18", "title": "Test film", "domain": domain_id}
    script = {
        "schema": "jjv/script/v1",
        "film_id": "n18",
        "title": "Test film",
        "duration_s": 20,
        "fps": domain["frame_rates"]["delivery_fps"],
        "structure": {"intro": {"duration_s": 1}},
        "shots": [{"id": "S01_A", "speaker": "speaker", "speech_text": "Hello.",
                   "duration_s": 20, "visual": "A speaker."}],
        "vocabulary_cards": [],
        "character_references": {"speaker": {"speech_allowed": True}},
    }
    return script, episode, domain


@pytest.mark.parametrize("sections", [None, {}, {"logo_hold": {"min": 24, "max": 48}}],
                         ids=["missing-sections", "empty-sections", "missing-pause"])
def test_derive_refuses_missing_pause_policy(sections):
    script, episode, domain = _inputs("newtecons_live_action")
    domain["delivery"].pop("sections", None)
    if sections is not None:
        domain["delivery"]["sections"] = sections

    with pytest.raises(Refused, match=r"delivery\.sections\.pause_native"):
        derive(script, episode, domain)


def test_derive_preserves_authored_pause_when_policy_exists():
    script, episode, domain = _inputs("jenniejoy_cartoon_3d")
    docs = derive(script, episode, domain)

    assert docs["contract-inputs.json"]["lines"] == [{"id": "S01_A", "wav_s": 19.75}]

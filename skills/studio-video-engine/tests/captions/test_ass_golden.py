"""Golden byte-exact cho engine.captions.ass (ban chuyen tu .karaoke-verb-stage; golden doc tai cho, khoa bang sha256)."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from engine.captions.ass import DEFAULT_HIGHLIGHT, cues_to_ass, cues_to_srt, words_to_cues
from engine.core.io import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[5]
GOLDEN_DIR = (REPO_ROOT / "production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s"
              / "REVIEW/2026-10-31-H3-options/C_turbo8HD_1280x704_DA-CHON-C2")
TIMING = GOLDEN_DIR / "timing-v001-recognition-attempt/WORD-TIMING.json"
GOLDEN = {
    GOLDEN_DIR / "S02_A_C2_karaoke.ass": "2eacdcebf977d13e54efb8f1184abce8bcb045e1908d00279121d316e821e5cb",
    GOLDEN_DIR / "S02_A_C2_karaoke_xanh.ass": "50b019322f7672eec504bc5c0a12d7ec0584d9dfa5a6c14950c01db2e4026751",
    TIMING: "0bcbceced99cb416fab151a5b14b68be56991865f472ded1045520310e7468c8",
}


@pytest.fixture(scope="module")
def cues():
    for path, digest in GOLDEN.items():
        assert sha256_file(path) == digest, f"golden input drifted: {path}"
    return words_to_cues(json.loads(TIMING.read_text(encoding="utf-8")))


def test_golden_yellow_byte_exact(cues) -> None:
    assert cues_to_ass(cues, highlight="#FFCC00", title="NEWTECONS S02_A karaoke review", title_suffix=" (FALLBACK: ASS from jjv WORD-TIMING.json, not remotion-kit)").encode("utf-8") == (GOLDEN_DIR / "S02_A_C2_karaoke.ass").read_bytes()


def test_golden_blue_byte_exact_and_title_follows_shot(cues) -> None:
    assert cues_to_ass(cues, highlight="0B4FD9", title="NEWTECONS S02_A karaoke review", title_suffix=" (FALLBACK: ASS from jjv WORD-TIMING.json, not remotion-kit)").encode("utf-8") == (GOLDEN_DIR / "S02_A_C2_karaoke_xanh.ass").read_bytes()
    other = cues_to_ass(cues, title="NEWTECONS S03_B karaoke review")
    assert "Title: NEWTECONS S03_B karaoke review\n" in other and "S02_A" not in other


def test_default_highlight_nfc_and_plain_srt(cues) -> None:
    ass = cues_to_ass(cues).encode("utf-8")
    words = " ".join(word.text for cue in cues for word in cue.words)
    srt = cues_to_srt(cues)
    assert DEFAULT_HIGHLIGHT == "#0B4FD9"
    assert b"Style: Karaoke,Arial,60,&H00D94F0B," in ass
    assert unicodedata.is_normalized("NFC", words)
    assert srt.startswith("1\n00:00:00,210 --> 00:00:01,160\n")
    assert "\\k" not in srt and srt.endswith("\n\n")

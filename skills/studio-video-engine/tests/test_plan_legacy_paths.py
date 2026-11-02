"""``jjv plan explain`` when the inputs name files by absolute paths (receipts and mix plans do):

* a receipt whose mix plan is NOT on disk makes ``audio.mix`` (and what hangs off it) UNCERTAIN, never CHANGED;
* a receipt plan under a retired root (``machine.legacy_roots``) is read where it lives now -> UNCHANGED;
* the fingerprint hashes no absolute path string: the same plan content in another directory is UNCHANGED.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_plan_support as S
from engine.config import loader
from engine.core.io import sha256_file
from engine.plan.model import strip
from test_plan_support import rows, run


def _receipt(version: Path, plan: Path) -> None:
    receipt = {"separate_deliverables": {"mix_wav": {"plan": str(plan), "plan_sha256": sha256_file(plan),
                                                     "sha256": S.sha("mix-wav-A")}}}
    (version / "RECEIPT.json").write_text(json.dumps(receipt), encoding="utf-8")


def _plan_file(folder: Path, plan: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "mix-plan-v014.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_a_receipt_plan_that_is_not_on_disk_makes_audio_mix_uncertain_not_changed(tmp_path: Path) -> None:
    plan = _plan_file(tmp_path / "gone", S.mix_plan())
    old = S.write_version(tmp_path, "old", S.base_config())
    _receipt(old, plan)
    plan.unlink()                                                        # the receipt still names it
    new = S.write_version(tmp_path, "new", S.base_config(), plan=S.mix_plan())
    doc = run(old, new, target="all")
    mix = rows(doc, kind="audio.mix")["audio.mix"]
    assert mix["status"] == "UNCERTAIN" and mix["action_code"] == "not_comparable" and mix["est_seconds"] is None
    assert any("not on disk" in line for line in mix["why"]) and "+plan" not in mix["leaves"]
    for node in ("mux", "qa.av", "mux.master", "film.downscale.2k"):
        row = next(r for r in doc["rows"] if r["node"] == node)
        assert row["status"] == "UNCERTAIN" and any("audio.mix" in line for line in row["why"]), node
    assert doc["summary"]["uncertain_nodes"] == ["audio.mix", "mux", "qa.av", "mux.master", "film.downscale.2k"]
    assert doc["summary"]["nodes_changed"] == 0 and doc["summary"]["est_seconds_total"] == 0.0
    assert doc["headline"][2].startswith("audio: not comparable")
    assert all(r["status"] == "UNCHANGED" for r in doc["rows"] if r["kind"] in ("composite.segment", "composite.master"))
    assert any("not on disk" in w for w in doc["warnings"])
    # the other way round (the NEW side's plan is the one that is gone) is just as uncertain
    assert rows(run(new, old, target="all"), kind="audio.mix")["audio.mix"]["status"] == "UNCERTAIN"


def test_a_changed_segment_beside_an_uncertain_mix_is_still_changed_and_the_mux_names_both(tmp_path: Path) -> None:
    plan = _plan_file(tmp_path / "gone", S.mix_plan())
    old = S.write_version(tmp_path, "old", S.base_config())
    _receipt(old, plan)
    plan.unlink()
    moved = S.mutate(S.base_config(), lambda c: S.shot_of(c, "S02_A")["words"][0].update(startF=300))
    new = S.write_version(tmp_path, "new", moved, plan=S.mix_plan())
    doc = run(old, new)
    assert rows(doc, kind="composite.segment", status="CHANGED")
    mux = rows(doc, kind="mux")["mux"]
    assert mux["status"] == "CHANGED" and any("not comparable" in line for line in mux["why"])
    assert "audio.mix changed" not in mux["why"]


def test_a_receipt_plan_under_a_legacy_root_is_read_where_it_lives_now(tmp_path: Path, monkeypatch) -> None:
    old_root, new_root = tmp_path / "retired-drive" / "03 Voice", tmp_path / "current-drive" / "03 Voice"
    plan = _plan_file(new_root / "ep" / "review-hd-v014", S.mix_plan())
    machine = tmp_path / "machine.json"
    machine.write_text(json.dumps({"legacy_roots": {str(old_root): str(new_root)}}), encoding="utf-8")
    monkeypatch.setattr(loader, "DEFAULT_MACHINE_PATH", machine)
    old = S.write_version(tmp_path, "old", S.base_config())
    recorded = old_root / "ep" / "review-hd-v014" / "mix-plan-v014.json"
    _receipt(old, plan)
    receipt = json.loads((old / "RECEIPT.json").read_text(encoding="utf-8"))
    receipt["separate_deliverables"]["mix_wav"]["plan"] = str(recorded)       # as a shipped receipt records it
    (old / "RECEIPT.json").write_text(json.dumps(receipt), encoding="utf-8")
    new = S.write_version(tmp_path, "new", S.base_config(), plan=S.mix_plan())
    doc = run(old, new, target="all")
    assert {r["status"] for r in doc["rows"]} == {"UNCHANGED"}
    assert Path(doc["old"]["sources"]["mix_plan"]) == plan and doc["summary"]["uncertain_nodes"] == []
    assert not any("not on disk" in w for w in doc["warnings"])


def test_the_same_plan_content_in_another_directory_is_unchanged(tmp_path: Path) -> None:
    cue = {"cue_id": "SFX-04", "file": "C:/old/sfx/SFX-04.wav", "file_sha256": S.sha("sfx-04"), "frame": 160}
    old = S.write_version(tmp_path, "old", S.base_config(), plan={**S.mix_plan(), "sfx_cues_used": [cue]})
    moved = {**cue, "file": "E:/moved/sfx/SFX-04.wav"}
    new = S.write_version(tmp_path, "new", S.base_config(), plan={**S.mix_plan(), "sfx_cues_used": [moved]})
    doc = run(old, new)
    assert rows(doc, kind="audio.mix")["audio.mix"]["status"] == "UNCHANGED"
    assert {r["status"] for r in doc["rows"]} == {"UNCHANGED"}
    other = {**moved, "file_sha256": S.sha("sfx-04-re-recorded")}
    new2 = S.write_version(tmp_path, "new2", S.base_config(), plan={**S.mix_plan(), "sfx_cues_used": [other]})
    mix = rows(run(old, new2), kind="audio.mix")["audio.mix"]
    assert mix["status"] == "CHANGED" and any(x.startswith("plan.sfx_cues_used[0].file_sha256") for x in mix["leaves"])
    assert not any(x.startswith("plan.sfx_cues_used[0].file ") for x in mix["leaves"])


def test_strip_drops_only_file_references_whose_sibling_sha_is_their_identity() -> None:
    sha = S.sha("bytes")
    value = {"file": "C:\\a\\b.wav", "file_sha256": sha,                      # identity is the sha: the path is dropped
             "icon": {"icon_path": "D:/x/i.png", "icon_sha256": sha},
             "card": {"v002_path": "D:/x/v2.png", "path": "D:/x/v1.png", "sha256": sha, "v002_sha256": sha},
             "mix_plan": "D:/x/mix-plan.json", "mix_plan_sha256": sha,          # <key>_sha256 beside a non path-ish key
             "loose": {"path": "D:/x/no-sha.mp4"},                               # a file reference with no sha: kept as written
             "rel": {"file": "clips/a.wav"},
             "text_en": "/home", "ipa": "/mɪlk/", "unc": "\\\\server\\share", "url": "http://127.0.0.1:8188", "n": 3,
             "list": ["D:/x/y.wav", "z.wav"]}
    out = strip(value, frozenset())
    assert "file" not in out and out["file_sha256"] == sha
    assert out["icon"] == {"icon_sha256": sha} and out["card"] == {"sha256": sha, "v002_sha256": sha}
    assert "mix_plan" not in out and out["mix_plan_sha256"] == sha
    assert out["loose"] == {"path": "D:/x/no-sha.mp4"} and out["rel"] == {"file": "clips/a.wav"}
    assert out["text_en"] == "/home" and out["ipa"] == "/mɪlk/" and out["unc"] == "\\\\server\\share"   # text is content
    assert out["url"] == "http://127.0.0.1:8188" and out["n"] == 3 and out["list"] == ["D:/x/y.wav", "z.wav"]
    assert value["file"] == "C:\\a\\b.wav"                                   # the input is not mutated
    bound = strip({"loose": {"path": "D:/x/no-sha.mp4"}}, frozenset(), lambda key, text: {"content_sha256": sha})
    assert bound == {"loose": {"path": {"content_sha256": sha}}}            # a binder gives a sha-less reference its content


def test_display_text_that_looks_like_a_path_is_content_and_changes_the_segment(tmp_path: Path) -> None:
    """N60: ``end_plate.text_en`` is rendered (remotion-kit ending.jsx); ``outro_cards[].ipa`` starts with ``/`` too."""
    base = S.mutate(S.base_config(), lambda c: (c["motion"]["ending"]["end_plate"].update(text_en="/home"),
                                                 c["outro_cards"][0].update(ipa="/ˈælfə/")))
    old = S.write_version(tmp_path, "old", base, plan=S.mix_plan())
    plate = S.write_version(tmp_path, "plate", S.mutate(base, lambda c: c["motion"]["ending"]["end_plate"].update(text_en="/work")),
                            plan=S.mix_plan())
    doc = run(old, plate)
    changed = rows(doc, kind="composite.segment", status="CHANGED")
    assert changed and all("ending" in r["layers"] for r in changed.values()) and doc["summary"]["nodes_changed"] > 0
    assert any("ending.plate.text_en /home -> /work" in leaf for r in changed.values() for leaf in r["leaves"])
    ipa = S.write_version(tmp_path, "ipa", S.mutate(base, lambda c: c["outro_cards"][0].update(ipa="/ˈbeɪtə/")), plan=S.mix_plan())
    changed = rows(run(old, ipa), kind="composite.segment", status="CHANGED")
    assert changed and all("cards" in r["layers"] for r in changed.values())
    assert rows(run(old, old), kind="composite.segment", status="CHANGED") == {}


def test_a_file_reference_without_a_sha_is_compared_by_its_content_or_is_uncertain(tmp_path: Path) -> None:
    a, b = tmp_path / "a" / "sfx.wav", tmp_path / "b" / "sfx.wav"
    for f in (a, b):
        f.parent.mkdir()
        f.write_bytes(b"same bytes")
    old = S.write_version(tmp_path, "old", S.base_config(), plan={**S.mix_plan(), "sfx_cues_used": [{"cue_id": "SFX-01", "file": str(a), "frame": 10}]})
    new = S.write_version(tmp_path, "new", S.base_config(), plan={**S.mix_plan(), "sfx_cues_used": [{"cue_id": "SFX-01", "file": str(b), "frame": 10}]})
    assert rows(run(old, new), kind="audio.mix")["audio.mix"]["status"] == "UNCHANGED"       # same bytes, other folder
    b.write_bytes(b"other bytes")
    mix = rows(run(old, new), kind="audio.mix")["audio.mix"]
    assert mix["status"] == "CHANGED" and any(x.startswith("plan.sfx_cues_used[0].file") for x in mix["leaves"])
    b.unlink()
    mix = rows(run(old, new), kind="audio.mix")["audio.mix"]
    assert mix["status"] == "UNCERTAIN" and any(str(b) in line for line in mix["why"])

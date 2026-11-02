"""``jjv timing words``: recognition -> onset correction on every word -> Q1 gate, three write-once files.

Outputs in ``--out``: ``WORD-TIMING.json`` (same layout as the v003/v004 word-timing documents),
``WORD-TIMING-QA.json`` (every word's audit row, the line-first rows, Q1 rows + negative control) and
``timing-receipt.json`` (input/output shas, recipe, recognition source; no timestamp).  A Q1 FAIL still
writes the files (they are the evidence) and ends exit 1; ``UNTESTABLE`` ends exit 2.

Times come from faster-whisper (``recognizer``) or, with ``supplied``, from an existing word-timing
document (its lines are re-checked and re-corrected; used for parity and for re-running the rules).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterable

from ..core.errors import Refused
from ..core.io import canonical_sha256, write_json_once
from .dialogue import word_rows
from .firstword import calibrate_last_end
from .gate import run_q1, sound_lookup
from .recipe import TimingRecipe
from .recognise import Recognizer, pair_words, script_tokens
from .wavs import BoundWav, bind_wavs
from .words import correct_entry, moved_summary, rule_block

TIMING_FILE, QA_FILE, RECEIPT_FILE = "WORD-TIMING.json", "WORD-TIMING-QA.json", "timing-receipt.json"
QA_SCHEMA, RECEIPT_SCHEMA = "jjv/timing-words-qa/v1", "jjv/timing-words-receipt/v1"


def _supplied_words(line: dict, supplied: dict[str, dict]) -> tuple[list[dict], dict]:
    """The words of an existing document for this line; text or WAV mismatch is Refused."""
    entry = supplied.get(line["id"])
    if entry is None:
        raise Refused(f"{line['id']}: not present in the supplied word timing")
    spelled = " ".join(w["raw_text"] for w in entry["words"])
    if spelled != line["speech_text"]:
        raise Refused(f"{line['id']}: supplied words spell {spelled!r}, the dialogue says {line['speech_text']!r}")
    declared = (entry.get("audio") or {}).get("sha256")
    if declared != line["audio"]["sha256"]:
        raise Refused(f"{line['id']}: supplied timing was made on WAV {declared}, the dialogue binds {line['audio']['sha256']}")
    return copy.deepcopy(entry["words"]), copy.deepcopy(entry)


def _fresh_entry(line: dict, words: list[dict], record: dict, duration_s: float, fps: float) -> dict:
    offset = line["audio"]["offset_frames"]
    audio = {**line["audio"], "duration_seconds": round(duration_s, 3), "offset_seconds": offset / fps}
    carried = {k: line[k] for k in ("speaker", "start_frame", "end_frame_exclusive", "speech_text", "en_markup",
                                    "target_keywords") if k in line}
    return {"id": line["id"], **carried, "audio": audio, "recognition": record, "word_count": len(words), "words": words}


def recognise_line(line: dict, bound: BoundWav, recognizer: Recognizer, recipe: TimingRecipe, fps: float,
                   vocabulary: list[dict]) -> tuple[list[dict], dict]:
    """Words of one line from recognition, plus the recognition record of the entry."""
    rec = recipe.block("recognition")
    heard = recognizer(bound.path, line["speech_text"])
    tokens = script_tokens(line["speech_text"])
    paired = pair_words(tokens, heard.words, rec["accept_similarity"], line["id"])
    method = f"whisper-{rec['model_label']}"
    words = word_rows(line, paired, vocabulary, fps, bound.sound.duration_s, method)
    words, end_report = calibrate_last_end(bound.sound, words, line["start_frame"], line["end_frame_exclusive"],
                                           recipe.block("first_word"), fps)
    record = {"engine": rec["engine"], "model": rec["model_label"], "script_word_count": len(tokens),
              "recognized_word_count": len(heard.words), "exact_sequence": [h.normalized for h in heard.words] == [t["normalized"] for t in tokens],
              "transcript": heard.transcript, "last_end_calibration": end_report, **heard.info}
    return words, record


def run_words(*, episode_id: str, fps: float, root: Path, lines: list[dict], vocabulary: list[dict],
              recipe: TimingRecipe, recognizer: Recognizer | None, supplied: dict | None, out: Path | None,
              allow: Iterable[Path | str] = (), dialogue_sha: str | None = None, first_word: bool = True) -> dict:
    """Run the three steps; returns the summary (``ok``, ``verdict``, counts, hashes). ``out=None`` writes nothing."""
    if (recognizer is None) == (supplied is None):
        raise Refused("exactly one source of word times is needed: recognition or a supplied word timing")
    bound = bind_wavs([l for l in lines if l["speech_text"]], root, allow)
    by_id = {e["id"]: e for e in (supplied or {}).get("entries", [])}
    entries, audits = [], []
    for line in lines:
        if not line["speech_text"]:
            entries.append({"id": line["id"], "start_frame": line["start_frame"], "end_frame_exclusive": line["end_frame_exclusive"],
                            "speech_text": "", "audio": line["audio"], "word_count": 0, "words": []})
            continue
        sound = bound[line["id"]].sound
        if supplied is not None:
            words, entry = _supplied_words(line, by_id)
        else:
            words, record = recognise_line(line, bound[line["id"]], recognizer, recipe, fps, vocabulary)
            entry = _fresh_entry(line, words, record, sound.duration_s, fps)
        fixed, audit = correct_entry(line["id"], (line["start_frame"], line["end_frame_exclusive"]), words, sound,
                                     recipe.data, fps, first_word=first_word)
        entry["words"] = fixed
        entry["first_word_rule"] = audit["first_word"]
        entries.append(entry)
        audits.append(audit)
    rows = [row for audit in audits for row in audit["rows"]]
    spoken = [e for e in entries if e["words"]]
    q1 = run_q1(spoken, sound_lookup(bound), recipe.block("q1"), fps)
    timing = _document(episode_id, fps, entries, vocabulary, recipe, rows, supplied, recognizer is None)
    qa = {"schema": QA_SCHEMA, "rule": rule_block(recipe.data), "first_word_rows": [a["first_word"] for a in audits],
          "words": rows, "q1": q1}
    summary = {"ok": q1["verdict"] == "PASS", "verdict": q1["verdict"], "words": len(rows),
               "words_moved": len(moved_summary(rows)), "moved": moved_summary(rows),
               "q1": {"summary": q1["summary"], "negative_control": q1["negative_control"]["status"],
                      "control_detected": q1["negative_control"]["detected"]},
               "source": "supplied" if supplied is not None else "recognition"}
    if out is not None:
        summary["files"] = _write(out, timing, qa, summary, recipe, dialogue_sha, supplied, bound)
    return summary


def _document(episode_id: str, fps: float, entries: list[dict], vocabulary: list[dict], recipe: TimingRecipe,
              rows: list[dict], supplied: dict | None, from_supplied: bool) -> dict:
    moved = moved_summary(rows)
    doc = {"schema": recipe.data["document_schema"], "generator": "jjv timing words", "episode_id": episode_id, "fps": fps,
           "timing_origin": "Each dialogue WAV start; review delivery frame mapping is added.",
           "frame_contract": "start_frame inclusive; end_frame/end_frame_exclusive is exclusive.",
           "recipe": {"id": recipe.recipe_id, "sha256": recipe.sha256}, "entries": entries,
           "onset_fix_all_words": {"rule": rule_block(recipe.data), "words_moved": len(moved), "moved": moved}}
    if vocabulary:
        doc["vocabulary_icons"] = [{"term": v["term"], "icon": v["icon"]} for v in vocabulary]
    if from_supplied and supplied is not None:
        doc["vocabulary_icons"] = supplied.get("vocabulary_icons", doc.get("vocabulary_icons", []))
        doc["generated_from"] = {"schema": supplied.get("schema"), "words": sum(len(e["words"]) for e in supplied["entries"])}
    return doc


def _write(out: Path, timing: dict, qa: dict, summary: dict, recipe: TimingRecipe, dialogue_sha: str | None,
           supplied: dict | None, bound: dict[str, BoundWav]) -> dict:
    out = Path(out)
    timing_sha = write_json_once(out / TIMING_FILE, timing, mode="utf8")
    qa["timing"] = {"file": TIMING_FILE, "sha256": timing_sha}
    qa_sha = write_json_once(out / QA_FILE, qa, mode="utf8", stamp=True)
    receipt = {"schema": RECEIPT_SCHEMA, "ok": summary["ok"], "verdict": summary["verdict"], "source": summary["source"],
               "inputs": {"dialogue_sha256": dialogue_sha, "recipe": {"id": recipe.recipe_id, "sha256": recipe.sha256},
                          "supplied_timing_canonical_sha256": canonical_sha256(supplied, mode="utf8") if supplied else None,
                          "wavs": [{"id": n, "path": b.shown, "sha256": b.sha256} for n, b in bound.items()]},
               "outputs": {TIMING_FILE: timing_sha, QA_FILE: qa_sha},
               "counts": {"words": summary["words"], "words_moved": summary["words_moved"]},
               "q1": {"verdict": summary["verdict"], **summary["q1"]}}
    receipt_sha = write_json_once(out / RECEIPT_FILE, receipt, mode="utf8", stamp=True)
    return {TIMING_FILE: timing_sha, QA_FILE: qa_sha, RECEIPT_FILE: receipt_sha}

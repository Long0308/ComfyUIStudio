"""Hash-bound receipt/CPU ASR timing and single-active-word ASS for review cuts.

No media is trimmed or retimed here. audio_offset_s is a delay within the slot;
timing_receipt_offset_s applies only to receipt timestamps, not fresh ASR.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

MODEL_PATH = next(Path('J:/2.Model-AI-Local/HuggingFace/hub/models--Systran--faster-whisper-small/snapshots').iterdir())
_MODEL = None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFC", text).casefold()
                   if unicodedata.category(c)[0] in "LN")


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_words(items: list) -> list[dict]:
    result = []
    for item in items:
        word = item.get("word", item.get("w", item.get("text", item.get("raw_text", ""))))
        start = item.get("start", item.get("s", item.get("start_s")))
        end = item.get("end", item.get("e", item.get("end_s")))
        if not str(word).strip() or start is None or end is None:
            raise ValueError("Unsupported word timing fields")
        start, end = float(start), float(end)
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError("Invalid word timing interval")
        pieces = str(word).split()
        for index, piece in enumerate(pieces):
            result.append({"word": piece,
                           "start": start + (end - start) * index / len(pieces),
                           "end": start + (end - start) * (index + 1) / len(pieces),
                           "split_asr_token": len(pieces) > 1})
    return result


def _receipt_words(path: Path, source_sha: str, shot: str) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    candidates = [data]
    if isinstance(data.get("selected"), dict):
        candidates.insert(0, data["selected"])
    candidates.extend(entry for entry in data.get("entries", [])
                      if entry.get("id", entry.get("shot")) == shot)
    for record in candidates:
        if not isinstance(record.get("words"), list):
            continue
        hashes = [record.get("sha256"), record.get("mp4_sha256")]
        for field in ("audio", "media", "wav", "source"):
            if isinstance(record.get(field), dict):
                hashes.append(record[field].get("sha256"))
        if source_sha not in hashes:
            continue
        return _read_words(record["words"])
    raise ValueError("No supported words record bound to the source SHA-256")


def _recognize(path: Path, digest: str, cache_dir: Path) -> dict:
    cache_path = cache_dir / (digest + ".small.cpu-int8.words.json")
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8-sig"))
        if cached.get("source_sha256") == digest and cached.get("model") == str(MODEL_PATH):
            return cached
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(str(MODEL_PATH), device="cpu", compute_type="int8",
                              cpu_threads=8, num_workers=1, local_files_only=True)
    segments, info = _MODEL.transcribe(str(path), language="vi", beam_size=5,
                                      word_timestamps=True, vad_filter=False,
                                      condition_on_previous_text=False)
    words, transcript = [], []
    for segment in segments:
        transcript.append(segment.text)
        for word in segment.words or []:
            words.append({"word": word.word, "start": word.start,
                          "end": word.end, "probability": word.probability})
    data = {"source_sha256": digest, "model": str(MODEL_PATH),
            "device": "cpu", "compute_type": "int8", "cpu_threads": 8,
            "num_workers": 1, "language": info.language,
            "transcript": " ".join(transcript).strip(), "words": words}
    _write_json(cache_path, data)
    return data


def _align(canon: str, words: list[dict], speech_window: float) -> tuple[list[dict], dict]:
    tokens = canon.split()
    lexical = [(index, _norm(word)) for index, word in enumerate(tokens) if _norm(word)]
    recognized = [word for word in words if _norm(word["word"])]
    matcher = SequenceMatcher(None, [word for _, word in lexical],
                              [_norm(word["word"]) for word in recognized], autojunk=False)
    matched, used = {}, set()
    for a, b, count in matcher.get_matching_blocks():
        for offset in range(count):
            matched[lexical[a + offset][0]] = recognized[b + offset]
            used.add(b + offset)
    aligned = []
    for index, text in enumerate(tokens):
        source = matched.get(index)
        aligned.append({"word": text, "start": source["start"] if source else None,
                        "end": source["end"] if source else None,
                        "estimated": source is None and bool(_norm(text)),
                        "nonlexical_display": not bool(_norm(text))})
    # Interpolate only unmatched runs. Every lexical interpolation remains marked.
    index = 0
    while index < len(aligned):
        if aligned[index]["start"] is not None:
            index += 1
            continue
        stop = index
        while stop < len(aligned) and aligned[stop]["start"] is None:
            stop += 1
        left = float(aligned[index - 1]["end"]) if index else 0.0
        right = float(aligned[stop]["start"]) if stop < len(aligned) else speech_window
        right = max(left, right)
        for pos in range(index, stop):
            aligned[pos]["start"] = left + (right - left) * (pos - index) / (stop - index)
            aligned[pos]["end"] = left + (right - left) * (pos - index + 1) / (stop - index)
        index = stop
    missing = [word["word"] for word in aligned if word["estimated"]]
    extra = [word["word"] for index, word in enumerate(recognized) if index not in used]
    return aligned, {"exact_lexical_sequence": not missing and not extra,
                     "missing_canon_words_estimated": missing, "extra_recognized_words": extra,
                     "canon_word_count": len(lexical), "recognized_word_count": len(recognized)}


def _stamp(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    hours, centiseconds = divmod(centiseconds, 360000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    secs, hundredths = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{hundredths:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _chunks(words: list[dict]):
    start = 0
    while start < len(words):
        end = min(start + 8, len(words))
        for pos in range(start + 5, min(start + 9, len(words))):
            if re.search(r"[.!?;]$", words[pos]["word"]):
                end = pos + 1
                break
        yield words[start:end]
        start = end


def _events(words: list[dict], slot_start: float, duration: float) -> list[str]:
    events = []
    for chunk in _chunks(words):
        boundaries = sorted({max(0.0, min(duration, float(w[key])))
                             for w in chunk for key in ("start", "end")})
        for left, right in zip(boundaries, boundaries[1:]):
            if right - left < 0.009:
                continue
            midpoint = (left + right) / 2
            active = next((i for i, w in enumerate(chunk)
                           if w["start"] <= midpoint < w["end"]
                           and not w["nonlexical_display"]), None)
            pieces = []
            for index, word in enumerate(chunk):
                value = _escape(word["word"])
                if index == active:
                    value = r"{\1c&HD94F0B&}" + value + r"{\1c&HFFFFFF&}"
                pieces.append(value)
            begin, finish = _stamp(slot_start + left), _stamp(slot_start + right)
            if begin != finish:
                events.append(f"Dialogue: 0,{begin},{finish},Karaoke,,0,0,0,,{' '.join(pieces)}")
    return events


def prepare_subtitles(slots: list, output_dir: Path) -> dict:
    """Write karaoke.ass/timing.json; return all mismatches and source evidence."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir.parent / "asr-cache"
    cache_dir.mkdir(exist_ok=True)
    records, events, digests = [], [], {}
    for slot in slots:
        canon = slot.get("speech_text")
        if not canon:
            continue
        shot = str(slot["shot"])
        source = Path(slot.get("audio_path") or slot["path"])
        record = {"shot": shot, "canon": canon, "audio_path": str(source),
                  "start_s": float(slot["start_s"]), "duration": float(slot["duration"])}
        try:
            if str(source) not in digests:
                digests[str(source)] = _sha(source)
            digest = digests[str(source)]
            record["source_sha256"] = digest
            words = None
            receipt = slot.get("timing_receipt")
            receipt_offset = 0.0
            if receipt:
                try:
                    words = _receipt_words(Path(receipt), digest, shot)
                    receipt_offset = float(slot.get("timing_receipt_offset_s", 0))
                    record.update(method="hash_bound_receipt", timing_receipt=str(receipt),
                                  timing_receipt_sha256=_sha(Path(receipt)))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    record["receipt_rejected"] = str(error)
            if words is None:
                result = _recognize(source, digest, cache_dir)
                words = _read_words(result["words"])
                record.update(method="local_faster_whisper_cpu_int8",
                              recognized_transcript=result["transcript"])
            offset = float(slot.get("audio_offset_s", 0)) + receipt_offset - float(slot.get("audio_in_s", slot.get("in_s", 0)))
            record["word_offset_s"] = offset
            aligned, mismatch = _align(str(canon), words,
                                       max(0.0, float(slot["duration"]) - offset))
            record.update(mismatch)
            clipped = []
            for word in aligned:
                word["start"] += offset
                word["end"] += offset
                if word["start"] < 0 or word["end"] > float(slot["duration"]):
                    clipped.append(word["word"])
                word["start"] = max(0.0, min(float(slot["duration"]), word["start"]))
                word["end"] = max(word["start"], min(float(slot["duration"]), word["end"]))
            record["words_clipped_by_slot"] = clipped
            record["words"] = aligned
            record["status"] = "timed" if mismatch["exact_lexical_sequence"] and not clipped else "review_required"
            events.extend(_events(aligned, float(slot["start_s"]), float(slot["duration"])))
        except Exception as error:
            # Preserve the film build while making a missing subtitle explicit.
            record.update(status="subtitle_failed", error=f"{type(error).__name__}: {error}")
        records.append(record)
    header = """[Script Info]
Title: NEWTECONS overnight review word karaoke
ScriptType: v4.00+
PlayResX: 2560
PlayResY: 1440
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial,60,&H00FFFFFF,&H00FFFFFF,&H00181818,&H90000000,0,0,0,0,100,100,0,0,1,3,1,2,120,120,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_path = output_dir / "karaoke.ass"
    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    summary = {"schema": "newtecons/overnight-word-timing/v1", "ass_path": str(ass_path),
               "event_count": len(events), "dialogue_slots": len(records),
               "review_required": sum(r["status"] != "timed" for r in records),
               "failed_slots": [r["shot"] for r in records if r["status"] == "subtitle_failed"],
               "note": "Missing canon words use estimated interpolation and are explicitly marked; no trim or retime.",
               "slots": records}
    _write_json(output_dir / "timing.json", summary)
    return summary

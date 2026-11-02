"""Voice -> ``jjv audio mix`` hand-off: the speech class of every receipt WAV and how the mix takes it.

The mix places speech by CLASS bus (``engine/audio/windows.py``): ``dialogue`` and ``vocabulary`` come from the
review config ``wav_bindings`` (the mix reads the class from the binding name: ``voc ...`` is vocabulary, else
dialogue), ``end_line`` and any other late line come through ``--extra-wav 'name|path|sha256|start_frame|class'``
and the ``brand_voice`` through ``--brand-voice F --brand-voice-sha256 H`` (its own stem, plays alone first).
Every finalize entry therefore carries ``class`` and a ``mix`` block with the exact sha-bound WAVs and the argument
shape; the start frame belongs to the timeline, not to the voice stage, so the template keeps ``{start_frame}``.
"""

from __future__ import annotations

from pathlib import Path

from .receipts import resolve_described

CLASSES = ("dialogue", "vocabulary", "end_line", "brand_voice")
HANDOFF_SCHEMA = "jjv/voice-mix-handoff/v1"


def binding_name(job: dict) -> str:
    """The name the mix and the review configs know the WAV by: ``voc <term>`` (vocabulary bus), ``dlg <shot>``
    (dialogue bus), the bare id for the late classes (they enter through --extra-wav / --brand-voice)."""
    if job["category"] == "vocabulary":
        return f"voc {job['source_id']}"
    return f"dlg {job['source_id']}" if job["category"] == "dialogue" else str(job["source_id"])


def mix_path(path: Path, episode_root: Path | None) -> tuple[str, bool]:
    """Episode-relative path (what the mix resolves) or absolute with ``outside_episode`` True (needs --allow-outside)."""
    resolved = Path(path).resolve()
    if episode_root is not None:
        try:
            return resolved.relative_to(Path(episode_root).resolve()).as_posix(), False
        except ValueError:
            pass
    return resolved.as_posix(), True


def _row(name: str, part: dict, speech: bool, entry: dict, out: Path, episode_root: Path | None) -> dict:
    path, outside = mix_path(resolve_described(part["path"], episode_root=episode_root, out=out), episode_root)
    rate = entry["editorial"]["metrics"]["sample_rate"]
    return {"name": name, "path": path, "sha256": part["sha256"], "outside_episode": outside,
            "samples": part.get("samples"), "duration_s": (part["samples"] / rate) if part.get("samples") else None,
            "speech_conditioning": bool(speech), "sample_rate": rate,
            "channels": entry["editorial"]["metrics"]["channels"]}


def _wav_rows(entry: dict, name: str, out: Path, episode_root: Path | None) -> tuple[list[dict], list[dict]]:
    """(the line's WAV rows, the H3 segment rows).  A split line enters the mix as its ONE full WAV (the segments
    concatenated, ``split.full``); the segments are the H3 conditioning inputs."""
    split = entry.get("split")
    if not split:
        return [_row(name, entry["receipt_wav"], True, entry, out, episode_root)], []
    segments = [_row(f"{name}:{s['label']}", s, s["receipt_wav"], entry, out, episode_root) for s in split["segments"]]
    return [_row(name, split["full"], True, entry, out, episode_root)], segments


def _usage(klass: str, rows: list[dict]) -> dict:
    if klass in ("dialogue", "vocabulary"):
        return {"via": "review-config wav_bindings", "binding": {"name": rows[0]["name"],
                "path": "<path>", "sha256": "<sha256>", "start_frame": "{start_frame}"}}
    if klass == "brand_voice":
        return {"via": "--brand-voice", "args": ["--brand-voice", rows[0]["path"], "--brand-voice-sha256",
                                                  rows[0]["sha256"]]}
    return {"via": "--extra-wav", "templates": [f"{r['name']}|{r['path']}|{r['sha256']}|{{start_frame}}|{klass}"
                                                for r in rows]}


def entry_handoff(entry: dict, job: dict, out: Path, episode_root: Path | None) -> dict:
    klass = job["category"]
    name = binding_name(job)
    rows, segments = _wav_rows(entry, name, out, episode_root)
    return {"class": klass, "bus": klass, "name": name, "wavs": rows, "h3_segments": segments,
            "usage": _usage(klass, rows), "needs_allow_outside": any(r["outside_episode"] for r in rows + segments)}


def receipt_handoff(entries: list[dict]) -> dict:
    """Receipt-level summary: which speech classes the mix will see and how many WAVs each."""
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["class"]] = counts.get(entry["class"], 0) + 1
    return {"schema": HANDOFF_SCHEMA, "classes": {k: counts[k] for k in sorted(counts)},
            "consumer": "jjv audio mix (engine/audio/windows.py: bus_of, load_extra, load_brand_voice)"}

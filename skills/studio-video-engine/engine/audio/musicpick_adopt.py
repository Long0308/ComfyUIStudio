"""``jjv audio music adopt``: the REQUIRED vocal step after a bed was generated, then register it in the library.

Input: the ``music-finalize.json`` of a generated plan (``music.finalize`` already loop-extended each take and ran the
vocal-free gate on it).  The chosen take (``--take``, else the receipt's stem):

* gate PASS: the bed is registered as it is;
* gate FAIL: Demucs ``no_vocals`` of the take's natural-length song -> loop-extend to the film -> gate AGAIN (a bed
  that still fails is NOT registered) -> separation residue -> register;
* gate NOT_RUN / ERROR: ``Refused`` (a bed whose vocal-free state is unknown never enters the library).

Registration (``library``): the bed is trimmed only DOWN so the true peak is <= -1 dBTP (the gain is recorded), copied into
``music-beds/`` write-once, a row with every number is appended and the episode is recorded in its ``used_in``; the
registry write is versioned with a backup.  Receipt: ``music-adopt.json`` (write-once) whose ``stem`` the mix reads.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from ..core.errors import Refused
from ..core.io import write_json_once, write_once
from ..voice.wavio import metrics, read_wav, wav_bytes
from . import dsp, library, loopext, loudness, musicpick, vocalgate, vocalstrip

ADOPT_FILE = "music-adopt.json"
ADOPT_SCHEMA = "jjv/audio-music-adopt/v1"
PEAK_CEILING_DBTP = -1.0
GENERATOR_LABEL = {"acestep": "acestep", "yue2": "yue2"}


def gate_numbers(gate: dict) -> dict:
    """The registry's ``vocal_gate`` block from a rule-v2 gate result (anything else cannot be registered honestly)."""
    if gate.get("rule") != "v2" or gate.get("metric") != "rms":
        raise Refused(f"the registry stores rule-v2 numbers (RMS-relative); this gate ran rule {gate.get('rule')!r}, "
                      f"metric {gate.get('metric')!r}")
    return {"vocal_minus_bed_rms_db": gate["vocals_relative_db"], "vocal_minus_bed_lufs_db": gate.get("vocals_relative_lufs_db"),
            "vocal_rms_dbfs": gate["vocals_rms_dbfs"], "windows_over_-40dBFS": gate["windows_over_limit"],
            "rule": "v2: vocal_minus_bed_rms_db <= -35 AND no 1 s window > -40 dBFS (lufs figure informational)",
            "pass": gate["status"] == "PASS"}


def _write_bed(path: Path, rate: int, audio: np.ndarray) -> str:
    return write_once(path, wav_bytes(rate, 2, 2, dsp.to_pcm16(audio).tobytes()))


def strip_route(out: Path, plan: dict, recipe, take: dict, *, gate, settings, strip_runner, vocal_runner,
                ffmpeg: str, spec: dict) -> dict:
    """no_vocals -> loop-extend -> re-gate -> residue.  Returns the evidence + ``bed`` (path, sha) or ``failed``."""
    rate, job = recipe.data["sample_rate"], take["job_id"]
    song_path = out / take["song_wav"]
    stems = vocalstrip.separate_two_stems(song_path, out / "strip" / job, settings, strip_runner)
    song, _ = vocalstrip.read_pcm(song_path)
    nov, _ = vocalstrip.read_pcm(out / "strip" / job / "no_vocals.wav")
    vox, _ = vocalstrip.read_pcm(out / "strip" / job / "vocals.wav")
    loop = recipe.data["loop_extend"]
    stereo = np.repeat(nov, 2, axis=1) if nov.shape[1] == 1 else nov
    bed, seam = loopext.extend(stereo, float(take["brief"]["bpm"]), plan["bed_target_s"], rate,
                               crossfade_s=loop["crossfade_s"], beats_per_bar=loop["beats_per_bar"],
                               intro_bars=loop["intro_bars"], window_bars=loop["window_bars"])
    path = out / "beds" / f"{job}-novocals-bed-{rate // 1000}k.wav"
    sha = _write_bed(path, rate, bed)
    regate = vocalgate.run(gate, path, out / "vocal-gate" / f"{job}-novocals", vocal_runner, ffmpeg)
    evidence = {"separation": stems, "loop_extend": seam, "regate": regate,
                "residue": vocalstrip.residue(song, nov, vox, rate, spec), "bed": {"path": str(path.relative_to(out)).replace("\\", "/"),
                                                                                  "sha256": sha, "duration_s": bed.shape[0] / rate}}
    evidence["failed"] = regate["status"] != "PASS"
    return evidence


def trimmed_bed(source: Path, out: Path, name: str, ffmpeg: str) -> dict:
    """The bed with its true peak at or under -1 dBTP (only ever lowered); written write-once under ``out/beds``."""
    wav = read_wav(source)
    pcm = np.frombuffer(wav.pcm, dtype="<i2").reshape(-1, wav.channels)
    loud = loudness.measure(pcm, wav.rate, ffmpeg)
    gain_db = 0.0 if loud.true_peak_dbtp is None else min(0.0, PEAK_CEILING_DBTP - loud.true_peak_dbtp)
    audio = dsp.to_stereo_float(pcm) * np.float32(dsp.db_to_gain(gain_db)) if gain_db < 0 else dsp.to_stereo_float(pcm)
    path = out / "beds" / name
    sha = _write_bed(path, wav.rate, audio) if gain_db < 0 else write_once(path, source.read_bytes())
    final = read_wav(path)
    after = loudness.measure(np.frombuffer(final.pcm, dtype="<i2").reshape(-1, final.channels), final.rate, ffmpeg)
    return {"path": path, "sha256": sha, "gain_applied_db": round(gain_db, 3), "duration_s": final.duration_s,
            "loudness": {"integrated_lufs": after.integrated_lufs, "true_peak_dbfs": after.true_peak_dbtp},
            "before_gain": {"integrated_lufs": loud.integrated_lufs, "true_peak_dbfs": loud.true_peak_dbtp}}


def bed_row(bed_id: str, file_name: str, trimmed: dict, *, generator: str, take: dict, brief: dict, energy: str | None,
            numbers: dict, domain_id: str, evidence: dict | None, receipt: str, prompt_id: str | None,
            used: dict) -> dict:
    description = (f"{generator}{' + Demucs no_vocals' if evidence else ''}: {brief['instruments']}, {brief['bpm']:g} BPM, "
                   f"{brief['key']} (engine pick for {used['film']})")
    return {"id": bed_id, "file": file_name, "sha256": trimmed["sha256"], "duration_s": round(trimmed["duration_s"], 2),
            "generator": generator + ("-demucs" if evidence else ""), "take": take["job_id"], "description_vi": description,
            "brief": {"bpm": brief["bpm"], "key": brief["key"], "instruments": brief["instruments"], "energy": energy},
            "loudness": {**trimmed["loudness"], "gain_applied_db": trimmed["gain_applied_db"]},
            "vocal_gate": {**numbers, "measured_on": "the bed before the peak trim" if trimmed["gain_applied_db"] < 0 else "the bed as stored"},
            "comfy_prompt_id": prompt_id, "source_manifest": receipt, "domain": domain_id,
            "strip": None if not evidence else {"residue": evidence["residue"], "separation": evidence["separation"]["model"],
                                                "first_gate": evidence.get("first_gate")},
            "used_in": [used], "status": "approved_vocal_free"}


def adopt(*, out: Path, plan: dict, recipe, finalized: dict, lib_dir: Path, film: str, domain_id: str, spec: dict,
          gate, settings, ffmpeg: str, strip_runner=subprocess.run, vocal_runner=subprocess.run, take_id: str | None = None,
          id_prefix: str, registry_schema: str, energy: str | None) -> dict:
    """Vocal step + registration; returns the receipt (also written write-once as ``music-adopt.json``)."""
    out = Path(out)
    if (out / ADOPT_FILE).exists():
        raise Refused(f"{out / ADOPT_FILE} exists: this folder was already adopted (receipts are write-once; use a new folder)")
    wanted = take_id or finalized["stem"]["take"]
    take = next((t for t in finalized["takes"] if t["job_id"] == wanted), None)
    if take is None:
        raise Refused(f"take {wanted!r} is not in the finalize receipt ({[t['job_id'] for t in finalized['takes']]})")
    first = take["vocal_gate"]
    if first["status"] in ("NOT_RUN", "ERROR"):
        raise Refused(f"take {wanted}: the vocal-free gate is {first['status']} ({first.get('reason')}); fix the separator "
                      "command and re-run finalize; a bed of unknown vocal state never enters the library")
    evidence = None
    if first["status"] == "PASS":
        source, final_gate, seam = out / take["bed"]["path"], first, take["loop_extend"]
    else:
        evidence = strip_route(out, plan, recipe, take, gate=gate, settings=settings, strip_runner=strip_runner,
                               vocal_runner=vocal_runner, ffmpeg=ffmpeg, spec=spec)
        evidence["first_gate"] = {k: first.get(k) for k in ("status", "vocals_relative_db", "vocals_rms_dbfs", "windows_over_limit",
                                                            "vocals_worst_1s_window_dbfs", "rule", "metric")}
        if evidence["failed"]:
            receipt = {"schema": ADOPT_SCHEMA, "episode_id": plan["episode_id"], "film": film, "status": "NO_VOCALS_GATE_FAIL",
                       "take": wanted, "first_gate": evidence["first_gate"], "strip": evidence, "registered": None}
            write_json_once(out / ADOPT_FILE, receipt, mode="ascii", stamp=True)
            return receipt
        source, final_gate, seam = out / evidence["bed"]["path"], evidence["regate"], evidence["loop_extend"]
    numbers = gate_numbers(final_gate)
    trimmed = trimmed_bed(source, out, f"{wanted}-library-48k.wav", ffmpeg)
    document, read_sha = library.load_registry(lib_dir, registry_schema)
    twin = next((b for b in document["beds"] if b["sha256"] == trimmed["sha256"]), None)
    if twin is not None:
        raise Refused(f"the bed is already registered as {twin['id']} (same sha256); nothing written")
    bed_id = library.next_bed_id(document, id_prefix)
    file_name = f"{bed_id}-{wanted}-full-48k.wav"
    library.add_bed_file(lib_dir, trimmed["path"], file_name)
    used = musicpick.used_entry(film, receipt=str(out / ADOPT_FILE), brief=take["brief"],
                                reason="generated: no library bed fitted")
    row = bed_row(bed_id, file_name, trimmed, generator=GENERATOR_LABEL.get(plan["recipe"]["id"].rsplit("#", 1)[-1], "yue2"),
                  take=take, brief=take["brief"], energy=energy, numbers=numbers, domain_id=domain_id, evidence=evidence,
                  receipt=str(out / ADOPT_FILE), prompt_id=take.get("prompt_id"), used=used)
    written = library.write_registry(lib_dir, library.with_bed(document, row), read_sha256=read_sha, schema=registry_schema)
    stem = musicpick.library_stem(lib_dir, row)
    stem["picked_by"] = "generated, gated" + (" (no_vocals stem, re-gated)" if evidence else " (raw take passed the gate)")
    receipt = {"schema": ADOPT_SCHEMA, "episode_id": plan["episode_id"], "film": film, "status": "BED_REGISTERED",
               "take": wanted, "bed_id": bed_id, "first_gate": {k: first.get(k) for k in ("status", "vocals_relative_db", "vocals_rms_dbfs",
                                                                                         "windows_over_limit", "rule", "metric")},
               "strip": evidence, "loop_extend": seam, "final_gate": final_gate, "gain_applied_db": trimmed["gain_applied_db"],
               "loudness_before_gain": trimmed["before_gain"], "bed_metrics": metrics(read_wav(trimmed["path"])),
               "registry": written, "stem": stem}
    write_json_once(out / ADOPT_FILE, receipt, mode="ascii", stamp=True)
    return receipt

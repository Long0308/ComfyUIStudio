"""Whisper word-timestamp worker: runs in the machine's speech-recognition Python, NOT in the engine's.

``python -I whisper_worker.py < request.json`` reads one JSON request on stdin and prints one JSON
document on stdout (stdlib + ``faster_whisper`` only; it imports nothing from the engine so a separate
interpreter can run it).  CPU only: ``CUDA_VISIBLE_DEVICES`` is emptied before the model loads and the
device in the request must be ``cpu``.  A failure is ``{"ok": false, "error": ...}`` and exit code 2; it
never prints made-up words.

Request: ``{model_dir, wav, prompt, language, device, compute_type, params{beam_size, best_of, patience,
temperature, vad_filter, condition_on_previous_text}}``.
Reply: ``{ok, words[{raw, start_s, end_s, probability}], transcript, versions{faster_whisper}}``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable


def run(request: dict, model_factory: Callable[..., Any] | None = None) -> dict:
    """Transcribe one WAV; ``model_factory(model_dir, device=, compute_type=, cpu_threads=)`` is injectable for tests."""
    if request.get("device") != "cpu":
        return {"ok": False, "error": f"device must be 'cpu', got {request.get('device')!r}"}
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    versions: dict[str, str] = {}
    if model_factory is None:
        try:
            import faster_whisper
            from faster_whisper import WhisperModel
        except Exception as error:  # noqa: BLE001 - reported as data, the parent decides
            return {"ok": False, "error": f"faster_whisper is not importable: {type(error).__name__}: {error}"}
        model_factory = WhisperModel
        versions["faster_whisper"] = str(getattr(faster_whisper, "__version__", "unknown"))
    try:
        model = model_factory(request["model_dir"], device="cpu", compute_type=request["compute_type"],
                              cpu_threads=max(1, min(8, (os.cpu_count() or 4) // 2)))
        params = request["params"]
        segments, _info = model.transcribe(
            request["wav"], language=request["language"], task="transcribe", beam_size=params["beam_size"],
            best_of=params["best_of"], patience=params["patience"], word_timestamps=True,
            initial_prompt=request["prompt"], condition_on_previous_text=params["condition_on_previous_text"],
            vad_filter=params["vad_filter"], temperature=params["temperature"])
        words, parts = [], []
        for segment in segments:
            parts.append(segment.text.strip())
            for word in segment.words or []:
                words.append({"raw": word.word, "start_s": float(word.start), "end_s": float(word.end),
                              "probability": float(word.probability)})
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    return {"ok": True, "words": words, "transcript": " ".join(p for p in parts if p).strip(), "versions": versions}


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
    except ValueError as error:
        print(json.dumps({"ok": False, "error": f"request is not JSON: {error}"}))
        return 2
    reply = run(request)
    print(json.dumps(reply, ensure_ascii=True))
    return 0 if reply["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())

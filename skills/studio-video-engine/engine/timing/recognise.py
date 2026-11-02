"""Step 1, recognition: faster-whisper word times (CPU, a separate Python) aligned to the script.

The speech-recognition Python and the model folder come from the machine (``machine.timing.python`` /
``machine.timing.model_dir`` or ``--python`` / ``--model``); a missing interpreter, model or package is
``Uncertain`` (exit 2) with the reason, and no word time is ever invented.  The script text stays
authoritative: recognised extras are dropped, a script word that cannot be paired with a recognised
word (similarity < ``accept_similarity``) makes the line Uncertain instead of getting an estimated time.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.errors import Uncertain
from ..core.winflags import no_window

WORKER = Path(__file__).with_name("whisper_worker.py")
# Chữ + số Unicode (không gạch dưới) và dấu kết hợp rời; khớp trên chuỗi đã NFC nên chữ Việt đủ dấu không bị cắt.
_WORD = r"(?:[^\W_]|[\u0300-\u036f])+"
_TOKEN = re.compile(rf"{_WORD}(?:'{_WORD})?")
COST_DELETE_SCRIPT, COST_INSERT_RECOGNISED = 1.22, 1.0


@dataclass(frozen=True)
class Heard:
    raw: str
    normalized: str
    start_s: float
    end_s: float
    probability: float


@dataclass(frozen=True)
class Recognition:
    words: tuple[Heard, ...]
    transcript: str
    info: dict


Recognizer = Callable[[Path, str], Recognition]  # (wav, prompt) -> what was heard


def _match(raw: str) -> str:
    """Từ đầu tiên của ``raw`` sau NFC (``""`` nếu không có); NFC và NFD cho cùng kết quả."""
    match = _TOKEN.search(unicodedata.normalize("NFC", raw))
    return match.group(0) if match else ""


def normalize_word(raw: str) -> str:
    return _match(raw).lower()


def script_tokens(text: str) -> list[dict]:
    """Script words in order: ``raw_text`` (as written), ``text`` (punctuation stripped), ``normalized``."""
    tokens = []
    for raw in text.split():
        text = _match(raw)
        if text:
            tokens.append({"raw_text": raw, "text": text, "normalized": text.lower()})
    return tokens


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _substitution(a: str, b: str) -> float:
    if a == b:
        return 0.0
    sim = similarity(a, b)
    return 0.30 if sim >= 0.70 else (0.65 if sim >= 0.45 else 1.15)


def align(script: list[str], heard: list[str]) -> list[tuple[int, int]]:
    """Needleman-Wunsch pairs ``(script_index, heard_index)``; ties prefer substitution, then script deletion."""
    n, m = len(script), len(heard)
    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0], back[i][0] = cost[i - 1][0] + COST_DELETE_SCRIPT, 1
    for j in range(1, m + 1):
        cost[0][j], back[0][j] = cost[0][j - 1] + COST_INSERT_RECOGNISED, 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = (cost[i - 1][j - 1] + _substitution(script[i - 1], heard[j - 1]),
                       cost[i - 1][j] + COST_DELETE_SCRIPT, cost[i][j - 1] + COST_INSERT_RECOGNISED)
            choice = options.index(min(options))
            cost[i][j], back[i][j] = options[choice], choice + 1
    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        op = back[i][j]
        if op == 1 and i > 0 and j > 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif op == 2 and i > 0:
            i -= 1
        elif op == 3 and j > 0:
            j -= 1
        else:
            break
    pairs.reverse()
    return pairs


def pair_words(tokens: list[dict], heard: tuple[Heard, ...], accept: float, label: str) -> list[Heard]:
    """The recognised word of every script word, in order; an unpaired script word is Uncertain."""
    pairs = dict(align([t["normalized"] for t in tokens], [h.normalized for h in heard]))
    missing = [t["text"] for i, t in enumerate(tokens)
               if i not in pairs or similarity(t["normalized"], heard[pairs[i]].normalized) < accept]
    if missing:
        raise Uncertain(f"{label}: recognition did not find script word(s) {missing}; no time is invented "
                        "(fix the audio/script or supply times with --recognised)",
                        evidence={"missing_script_words": missing, "heard": [h.raw for h in heard]})
    return [heard[pairs[i]] for i in range(len(tokens))]


def find_model_dir(path: str | Path) -> Path:
    """A folder holding ``model.bin``, or the newest snapshot below one; anything else is Uncertain."""
    root = Path(path)
    if not root.is_dir():
        raise Uncertain(f"speech-recognition model folder not found: {root}")
    if (root / "model.bin").is_file():
        return root
    snapshots = sorted((p for p in root.rglob("model.bin")), key=lambda p: p.stat().st_mtime, reverse=True)
    if snapshots:
        return snapshots[0].parent
    raise Uncertain(f"no model.bin under {root}")


def subprocess_recognizer(python: str | Path, model_dir: Path, recipe: dict, language: str) -> Recognizer:
    """A recognizer that runs ``whisper_worker.py`` with ``python -I`` (CPU, no network, no engine imports)."""
    interpreter = Path(python)
    if not interpreter.is_file():
        raise Uncertain(f"speech-recognition Python not found: {interpreter} (set machine.timing.python or --python)")
    params = {k: recipe[k] for k in ("beam_size", "best_of", "patience", "temperature", "vad_filter",
                                     "condition_on_previous_text")}

    def recognise(wav: Path, prompt: str) -> Recognition:
        request = {"model_dir": str(model_dir), "wav": str(wav), "prompt": prompt, "language": language,
                   "device": recipe["device"], "compute_type": recipe["compute_type"], "params": params}
        try:
            done = subprocess.run([str(interpreter), "-I", str(WORKER)], input=json.dumps(request), text=True,
                                  capture_output=True, timeout=float(recipe["timeout_seconds"]), check=False,
                                  creationflags=no_window())
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Uncertain(f"recognition worker did not run: {type(error).__name__}: {error}") from error
        try:
            reply = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as error:
            raise Uncertain(f"recognition worker gave no JSON (exit {done.returncode}): {done.stderr.strip()[-300:]}") from error
        if not reply.get("ok"):
            raise Uncertain(f"recognition failed: {reply.get('error')}")
        heard = tuple(Heard(w["raw"], normalize_word(w["raw"]), w["start_s"], w["end_s"], w["probability"])
                      for w in reply["words"])
        return Recognition(heard, reply["transcript"], {"versions": reply.get("versions", {}), "python": str(interpreter)})

    return recognise

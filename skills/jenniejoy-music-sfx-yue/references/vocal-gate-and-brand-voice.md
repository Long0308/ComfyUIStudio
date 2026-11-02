# Vocal-free gate + brand voice — numbers from ep04 T-A11 (2026-10-27)

Root folder: `production-local/JennieJoyKids-Story/04-milk-and-mom/audio/music-yue2-v002/`.

## Demucs venv

`production-local/engine/tools/demucs-venv` (uv, CPython 3.11.16): demucs 4.1.0, torch 2.14.1+cpu, torchaudio 2.11.0+cpu,
numpy 2.4.6, soundfile 0.14.0. Weights pulled by demucs from HF `adefossez/HTDemucs` →
`~/.cache/huggingface/hub/models--adefossez--HTDemucs/snapshots/cbc8a9b1…/955717e8.safetensors` (84 025 440 B,
sha256 `d9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd`). Command:
`demucs-venv/Scripts/python.exe -m demucs -n htdemucs --two-stems=vocals -d cpu -o <out> <wav>` → `<out>/htdemucs/<name>/{vocals,no_vocals}.wav` at 44.1 kHz.
Speed: 170 s bed ≈ 66 s on CPU.

## Gate results

| Bed | vocal − bed (LUFS) | vocal RMS dBFS | 1 s windows > −40 dBFS | Verdict | ASR on vocal stem |
|---|---|---|---|---|---|
| v001 NHAC-1 (YuE2 take2 loop) | −4.1 | −23.1 | 77 | FAIL | — |
| v001 NHAC-2 (YuE2 take3 loop, user pick) | −2.8 | −25.7 | 60 | FAIL | 131 s sung English nonsense |
| v001 NHAC-3 (YuE2 take1 loop) | −2.7 | −23.5 | 123 | FAIL | 177 s sung |
| V2A/V2B/V2C -tag and -inst raw takes (6) | −1.2 … −3.5 | −21.5 … −25.4 | 24 … 52 | FAIL ×6 | tag takes: "Jenny Joy Kids!" at 0.08–1.52 s then more singing |
| NHAC-V2-4/5/6 = no_vocals of V2A/B/C-inst, loop-extended, re-separated | −50.7 / −51.9 / −48.3 | −67 … −76 | 0 | PASS | — |
| ACE-Step 1.5 turbo pilot 120 s raw | −57.5 | −66.9 | 0 | PASS | — |
| ACE-V2-1 / ACE-V2-2 raw (120 s) | −46.3 / −54.5 | −64.4 / −58.9 | 0 / 0 | PASS | — |
| ACE-V2-3 (+glockenspiel) raw | −6.1 (LUFS, sparse-stem artefact; RMS −23.1) | −37.4 | 3 (37–38 s, 112–114 s) | FAIL → delivered as no_vocals | whisper: 0 segments (no words) |
| ACE-V2-3 no_vocals re-gated | −32.0 LUFS / RMS ≤ −35 | −51.7 | 0 | PASS (rule v2) | — |

**Rule v2 (after ACE-V2-3):** ebur128 integrated loudness gates out silence, so a vocal stem that is 99 % silent reports the
loudness of its 1 % and the "LUFS relative" figure is meaningless for sparse stems (ACE-V2-3 no_vocals: RMS −51.7 dBFS but
"−32 dB rel."). The gate therefore uses the whole-region RMS ratio `vocal_minus_bed_rms_db ≤ −35` plus the 1 s window rule;
the LUFS figure stays in the JSON as information (`vocal_gate.py` writes both and `rule: v2`).

Separation residue (`tools/residue_check.py`, original vs no_vocals in vocal-free windows of the raw take): V2A −35.5 dB mean
(max −17.1), V2B −31.9 (max −29.8), V2C −37.2 (max −22.7); in voiced windows −4.5…−5.4 dB (vocals removed, expected).

## ACE-Step 1.5 turbo graph (ran, 120 s)

`UNETLoader acestep_v1.5_turbo` → `ModelSamplingAuraFlow shift 3` → `KSampler 8 / cfg 1 / euler / simple`;
`DualCLIPLoader(qwen_0.6b_ace15, qwen_1.7b_ace15, type ace)` → `TextEncodeAceStepAudio1.5(tags, lyrics "[Instrumental]", seed,
bpm 108, duration 120, timesignature 4, language en, keyscale "F major", generate_audio_codes true, cfg_scale 2.0, temperature 0.85,
top_p 0.9)` + `ConditioningZeroOut`; `EmptyAceStep1.5LatentAudio 120 s`; `VAELoader ace_1.5_vae` → `VAEDecodeAudio` (48 kHz) →
`SaveAudio`. Measured: 40.6 s wall, nvidia-smi +6 814 MiB, output exactly 120.0 s, −11.5 LUFS / +1.0 dBTP raw.
Graph: `music-yue2-v002/workflows/ACE-V2-pilot-guitar-marimba/`; receipt `receipts/ACE-V2-pilot-guitar-marimba/`.

## Brand voice takes (VoiceStudio OmniVoice 0.5.6, Alice 8f1145d7)

| Take | instruct | ref | speed | F0 mean Hz | ASR |
|---|---|---|---|---|---|
| raw-A s11 | child, high pitch | profile | 0.95 | 397 | Jenny Joy's Kids |
| raw-B s22 | child, very high pitch | profile | 1.05 | 524 (too high) | Jenny joys kids |
| raw-C s33 | child, moderate pitch | profile | 0.85 | 431 | Jennie Joy's Kids |
| raw-D1 s44 | child, high pitch | profile | 1.0 | 447 | **Jimmy** Joy's Kids (reject) |
| raw-E s61 | child, high pitch | S03_B "creamy, fresh, and yummy!" | 1.15 | 363 | Jenny Joyce kids |
| raw-F s62 | child, high pitch | S03_B | 1.1 | 280 | Jennie Joy's Kids |
| raw-G/H s63/64 | child, high pitch | S04_B "Yes! I enjoy milk…" | 1.15/1.2 | 491/487 (too high) | Jenny Joyce/Joy's Kids |
| raw-I s65 | child, high pitch | S03_B | 1.2 | 375 | Jenny Joy's Kids |

## T-A12: fixing a rushed YuE2 sung tag (GIONG-C → GIONG-C2-A..D)

Diagnosis of GIONG-C (YuE2 V2A-tag vocal stem): voice onset 0.055 s with no breath, one continuous voiced burst 0.415–1.60 s,
"Jennie Joy" sung inside 0.84 s (~0.28 s per syllable, "Joy" swallowed); whisper fails on the raw stem AND on the full mix
("Jenny's like/your kids") → the slur is YuE2's delivery, not a Demucs attack artefact. Four new takes with an instrumental
`[Intro]` before `[Verse] Jennie Joy Kids!` (seeds 20261103–06, max 60 s, 24–51 s wall, +4.6…+6.0 GiB): one sang "Ginny, joy kit!"
clearly at 26 s inside the mix, but the isolated Demucs cut no longer passes ASR; three sang other words ("Oh", "You", "Thank you
very much") — YuE2 does not reliably place or pronounce a short brand line. What worked: the **cheap fix** on the existing C
source — one-beat lead-in (60/108 BPM = 0.556 s silence) + rubberband time-stretch of the first 0.4 s ×1.25 with
`formant=preserved` → GIONG-C2-B 2.35 s, ASR "Jenny Joy Kids" (pass), −16 LUFS / −4.7 dBTP. Stretching the whole first word
(0.84 s ×1.3 / ×1.5, variants A/C) read "Tiny Joy Kids!" / "Jenny's your kids!" — whisper on 2–3 s clips is unstable run to run
(same stem: "Ginny, joy kit!" then "Jini, Joykit!"), so treat ASR as a proxy and let the ear decide. Rule for next time: ask the
singer for a breath before the line (silence/beat), keep each syllable ≥ 0.18 s, and prefer slowing the attack over re-rolling seeds.

Alice dialogue reference (same estimator): S03_B mean 306 Hz, S04_B 347 Hz. Delivered readings: GIONG-A (raw-E sculpted) 1.575 s,
237 Hz, ASR "Jenny Joyce, kids."; GIONG-B (raw-I) 1.563 s, 307 Hz, "Jenny Joy's Kids."; GIONG-C (YuE2 tag) 1.652 s, 394 Hz,
"I need your kids!" (fail, labelled); GIONG-D (E+I+F chorus) 1.571 s, 301 Hz, "Jenny Joyce kids." All −16.0 LUFS, TP −2.8…−5.5 dBTP.

# boundaries.json - provenance of non-obvious values

## expect_silent[S06_B3].max_rms = 0.04 (was 0.06, changed in T-E28a round 3)

`max_rms` is the largest RMS (full scale) the EXPORT may have inside the silent shot's window
(f2110-f2160). It is an engine-bounded number: `0 < max_rms <= 0.05`
(`engine/qa/av.py` `SILENT_MAX_RMS_CEILING`, `schemas/boundaries.schema.json`).

Measurements (read-only, `review-hd-v010` export decoded mono 48 kHz, `engine.qa.av.window_rms`):

| quantity | value |
|---|---|
| bed RMS over f2110-f2160 (whole window) | 0.0279 |
| bed RMS per 5-frame slice in that window | 0.013 - 0.042 |
| quietest dialogue WAV in the episode (S06_B1, whole file) | 0.0731 |

Rule used: bed-relative, `max_rms = measured bed x sqrt(2)` = 0.0394, rounded to 0.04. A source as
loud as the bed itself raises the window by 3 dB and so crosses the bound; the quietest dialogue line
(0.0731, or 0.078 on top of the bed) crosses it with a factor of about 2. The old 0.06 let a 0.05-amplitude
tone (window RMS about 0.045) pass. The window is judged as a whole, so the 5-frame peak of 0.042 does not fail.
Re-measure the bed (and update this note) if the music bed under S06_B3 is remixed.

"""Collar-mark logo composite (port of the accepted staging tool ``ntclogo`` 0.2.0; CPU, OpenCV + ffmpeg).

Pipeline: domain gate -> asset sha gate -> seed box (explicit or auto-detected, fail-closed) -> KLT/RANSAC track
-> track gate (LEADING/TRAILING_LOSS, LOST_FRACTION_EXCEEDED, INTERPOLATED_GAP_TOO_LONG, WINDOW_MARGIN_VIOLATION)
-> per-frame composite -> encode (audio stream copy, packet hash check) -> edge-band gate -> write-once outputs + receipt.
Every refusal happens before the output is published; the first three happen before any pixel is decoded or encoded.
"""

PORTED_FROM = "ntclogo 0.2.0 (staging logo-composite-v002)"

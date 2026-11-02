"""Cinematic post grade: 3D LUT + optional soften / halation / grain (CPU, ffmpeg). Domain-neutral: no domain names here.

Order per frame: soften -> halation -> grain (its own layer) -> LUT. Every LUT must be declared by the domain
(``domain.post.grade.luts``) by file name and sha256; before/after stills are written for approval.
"""

RECEIPT_SCHEMA = "jjv/post-grade-receipt/v1"

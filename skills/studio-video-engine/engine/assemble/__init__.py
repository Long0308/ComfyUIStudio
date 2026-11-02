"""Domain-neutral master assembler (CPU only): EDL -> picture -> stems -> multitrack mux -> receipt.

Nothing in this package names a domain, an episode, a film or a machine path: every number
(master size, fps, review size, fonts, audio tracks, ref level) comes from the domain block
``delivery.assemble`` resolved by the caller.  The gate is ``delivery.assemble.enabled``.
"""

from . import edl, karaoke, proc, receipt, render, stems, timing  # noqa: F401

__all__ = ["edl", "karaoke", "proc", "receipt", "render", "stems", "timing"]

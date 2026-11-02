"""Engine-level health preflight for every GPU/ComfyUI execute path (T-E39).

Read-only probes only: ``docker version`` / ``docker inspect`` and ``GET /system_stats`` /
``/queue`` / ``/object_info/<class>``.  Nothing here submits, interrupts, frees memory, starts,
stops or restarts anything.  A failed check names itself and the operator's next step; a refusal
is ``Refused`` (exit 1) raised BEFORE any intent or POST, so nothing is ever queued.

Entry points: :func:`engine.health.preflight.require_ready` (call sites),
:func:`engine.health.preflight.run_preflight` (report only),
:func:`engine.health.preflight.dry_preflight` (fixture form, no HTTP / no docker),
``jjv health preflight`` (:mod:`engine.health.cli`).
"""

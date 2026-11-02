"""``jjv bridge serve``: a loopback HTTP bridge that lets a ComfyUI graph node start engine jobs on the host.

Routes (all but ``/v1/health`` need ``Authorization: Bearer <secret>``; the secret lives in ``<state>/secret``):

* ``POST /v1/images/codex`` -> a provenance-correct ``images prompt new`` + ``prompt confirm`` (the Run click is the
  confirmation, recorded as ``comfyui-run:<client_id>``), then N ``codex-exec`` library takes on the allow-listed
  account lanes; every PNG is copied (write-once) into ``<comfy input>/codex-lane/<job_id>/``.  Cloud GPT, not GPU.
* ``POST /v1/video/shot`` -> ``jjv video run|render|status`` as a DETACHED child (one at a time); never blocks.
* ``GET /v1/jobs/<id>`` -> the job document on disk.

Domain-neutral: the episode, the machine config and the account allow-list come from the caller.
"""

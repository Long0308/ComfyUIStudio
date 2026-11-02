# Explicit resolution tiers

`video plan --tier preview|fullhd|2k` defaults to `preview`.

| Tier | Pixels delivered | Source | Human gate |
|---|---|---|---|
| preview | 864x480 | H3 native graph, explicit width/height overrides | Existing GPU permission and domain qualification still required |
| fullhd | 1920x1080 | Upscale the approved 864x480 clips, center-crop without stretch | Approved preview cut and every source clip |
| 2k | 2560x1440 | Upscale the approved Full HD clips | Approved Full HD cut and every source clip |

Policy is `recipes/video/resolution-tiers-v001.json`. The old route's geometry numbers do not override a selected tier.
H3 generates preview pixels only in this path. The exceptional 1280x704 re-render for a face broken by upscale is a
separate pilot, not automatically selected by this flag. Higher tiers never re-generate previously approved pixels.

`plan.json`, every `plan-receipt.json`, render/run receipts and plan/render steplog settings record `tier` and
`resolution`; graph geometry is also frozen. `video run|render|upscale --tier T` asserts that frozen choice. Omit
the flag on those verbs to inherit the plan. A changed tier requires a new versioned output folder. Old plans
without a resolution tier are refused and must be re-planned; historic receipts are never rewritten.

## Human approval record

Pass an explicit path with `video plan --tier 2k --tier-approval <record.json>` (also required for `fullhd`).
Recommended permanent location after review: `<episode>/engine/approvals/resolution/fullhd-to-2k.json` or
`preview-to-fullhd.json`. There is no implicit search, token shortcut or record writer in this patch. During
staging, create no production approval: the example below is documentation, not evidence of user approval.

Minimum shape for 2K (replace placeholders with the actual user's review and hashes):

```json
{
  "schema": "jjv/video-tier-approval/v1",
  "episode_id": "<exact episode id>",
  "domain": "<exact domain id>",
  "shotlist_sha256": "<sha256 of the exact input shotlist bytes>",
  "source_tier": "fullhd",
  "target_tier": "2k",
  "status": "approved",
  "approved_by": "<person who watched>",
  "approved_at": "2026-11-01T10:00:00+07:00",
  "note": "<actual user approval of this Full HD cut for 2K>",
  "cut": {"path": "fullhd-cut.mp4", "sha256": "<cut sha256>"},
  "shots": {
    "S02_A": {"path": "S02_A-fullhd.mp4", "sha256": "<source clip sha256>"}
  }
}
```

`shots` must cover exactly every shot in this plan. For Full HD use `source_tier: preview` and
`target_tier: fullhd`. Relative media paths resolve against the approval file's parent. Absolute paths are
also accepted. The reader checks schema, status, episode, domain, shotlist hash, source/target tiers, human
name, nonempty note, past timezone-aware timestamp, actual cut/clip hashes and ffprobe dimensions. It freezes
the record hash in the plan and rechecks it and the media on execution/resume. It checks that the record bytes
did not change during validation. Names are an accidental-self-approval guard, not authenticated signatures.

This record permits a resolution promotion; it grants no GPU permission or backend qualification. The
existing qualified backend/GPU/machine-lock gates remain. A 2K adapter run additionally needs `2560x1440`
in the domain qualification receipt's `targets` array; no qualification is created by this patch. Default
backend `none` keeps higher-tier execution pending until a qualified backend is selected.

## Review and measurement

Preview completion retains the exact native bytes and writes a `native-preview` review receipt; it does not
upscale. ffprobe must report 864x480 before a preview becomes review-ready. `video accept` picks/rejects the
native preview through the existing H3 acceptance ledger. Promoted outputs have their own output-hash ledger
entry and do not pretend to have a new H3 adoption. Rejected output hashes remain banned across plan folders.

The historical state name `upscaled_1080` and legacy acceptance field names `output_1080_*` are retained for
compatibility; inspect `tier`, `target`, `backend` and measured output dimensions for actual size. A preview
review never promotes to Full HD automatically. A separate approved cut record is needed for each promotion.

This patch has CPU tests and graph-binding checks. It does not qualify H3, long-take, an upscale recipe, or
visual quality on a GPU.

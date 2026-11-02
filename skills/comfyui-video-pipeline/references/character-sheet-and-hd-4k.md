# Character sheets, named references and HD → QA → 4K

Applies to the NEWTECONS eight-actor, 160-image workflow. Detailed evidence: [2026-10-23 screenshot/local graph audit](../../../../docs/research/comfyui-character-sheet-audit-20261023/REPORT.md); executable-work planning data: [action plan](../../../../docs/research/comfyui-character-sheet-audit-20261023/actionplan.json).

## Learn from layout without fabricating compatibility

The supplied Qwen screenshot demonstrates per-character positive/negative panels and individual portrait SaveImage outputs. It does not expose a complete executable graph or establish checkpoint/LoRA compatibility. Its portrait negatives prohibit body/side/back/sheet views; never propagate them to tasks requiring those views. Do not globally forbid logos when task wardrobe requires NEWTECONS marks. Do not add fake conditioning ports. On the inspected FLUX2 Klein CFG1/ConditioningZeroOut route, a negative prompt panel does not become effective guidance merely by being visible.

The supplied MEW look sheet demonstrates coverage: hero face, head angles, expressions, full-body angles, material/accessory details and palette. Reuse this audit structure only. Keep actual NEWTECONS names, roles, original actor identity/body references and current task wardrobe. Do not copy example age, nationality, numerical body measurements or clothing into the cast.

## Asset contract

Each actor has stable ID/name/role, hero face, head-angle sources, body canonical front/three-quarter/profile/back, wardrobe/details/palette, ten facial-expression tasks and ten action tasks. Reference sheets, derived crops and review sheets are support artifacts, not extra completed tasks. Generate and save each deliverable PNG separately; assemble review sheets from accepted individual outputs.

Every reference has actual filename/path/hash, semantic role, actor ID, crop/transform provenance, uploaded path, loader ID, consumer input and a validated graph path to the selected output. English prompts name those real attached files and contain full actor/body/wardrobe/performance/camera/light descriptions. Avoid `Image1` shorthand and text-only claims of attachment. Visible groups, controls, status and preview titles are Vietnamese.

For CHAR08 preserve the original `CHAR_08_KYSU_TRE_NU_GOC_XOAY.png`, `CHAR_08_6_GOC_XOAY_GOI_CAM_4096.png` and `CHAR_08_ICON_FACE.png` reference chain. Extract single-view body/face crops with recorded coordinates rather than conditioning indiscriminately on a whole multi-person-looking sheet. Glasses, ponytail and selected body silhouette matter. Current microgrid shirt/collar-logo/no-lanyard instructions supersede older garment/accessory details visible in source images.

## Required canvas and execution order

`Ảnh tham chiếu → Model / prompt / thông số → Ảnh hoàn chỉnh HD → QA → 4K khi HD đạt`.

Use eight named workflows with twenty selectable tasks each. Retain separate body/pose and identity/expression conditioning responsibilities. Pose controls alone do not preserve body shape; face patches do not correct a wrong full-body base. Full English prompts remain visible and must match queued payloads. Submit only the selected task's reachable sinks.

1. Validate live nodes/models on 8188 and explicit active manifest revision. Resolve stale `active` pointer conflicts instead of silently choosing a filename. Produce a complete 3:4 HD candidate at least 1536×2048. Face patches are intermediate, even if their SaveImage is technically the last node of a patch graph. Record base resolution/reconstruction honestly.
2. Review the actual HD PNG/hash: identity, expression/action, body when visible, framing, garment structure, exact lettering/marks, hands, glasses, texture and integration. `UNKNOWN` blocks promotion just like `FAIL`; never claim hidden body/garment properties passed from a face-only crop. Expression must visibly change in eyes/cheeks/brows/mouth as specified, not just receive a different filename.
3. Only a current hash-bound HD PASS permits a separate 4K job from that accepted PNG to 3072×4096. Do not attach an unconditional upscale sink to a candidate graph and rely on a note box as a gate. Recheck 4K eyes/teeth/hair/fabric/lettering and identity. Native dimensions alone do not prove detail quality.

## Automatic run and publication contract

Use 8188, sequential GPU work, durable task/revision/job records, real prompt IDs, actual submitted API and GUI graph, source/model/output hashes, dimensions and seeds. On uncertain submission response, reconcile queue/history before retrying. A client ledger key is not proof that the server deduplicates requests.

Fetch output identified by actual history metadata; publish on the correct workflow result node/gallery and verify it displays. API completion does not guarantee the currently open UI has refreshed. Keep full executed and result-bound GUI revisions. Failed images remain inspectable with precise reasons. Automatically review and retry targeted branches within a bounded budget; unchanged repeated failure means reassess conditioning/dependencies, not an endless new-seed loop.

Separate generated, internally passed, published and user-accepted states. Never increment the 160 accepted-image count for a support sheet, a patch, a receipt, an enlarged failed image or a plan. Preserve historical outputs and replacement provenance. Do not silently switch to cloud or another port when a named local node is missing.

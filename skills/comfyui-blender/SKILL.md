---
name: comfyui-blender
description: "Phối hợp Blender MCP và ComfyUI MCP để dựng nhân vật, vật thể, bối cảnh 3D tái sử dụng cho hoạt hình JennieJoy 3D (game: ngoài phạm vi cho tới khi user quyết định); chuyển camera, render và control passes giữa hai công cụ; hỗ trợ render kiến trúc, kết cấu, MEP và thi công từ mô hình sẵn có (aec); với phim người thật NEWTECONS chỉ previz bố cục/camera bằng proxy, không tạo nhân vật. Có API cấu trúc không gian (scripts/scene_layout.py: brief JSON, validate, emit-bpy, set dùng chung, continuity giữa hai shot, placement-text) và mục Domain routing tách jenniejoy_cartoon_3d, newtecons_live_action và AEC."
---

# ComfyUI-Blender Studio

**Canonical source (2026-10-27):** this folder is the shared-engine skill ported from the Codex copy. On sync the Codex root becomes a pointer to this canonical skill; the pre-sync original is archived at `J:\1.JennieHomeSchool\03 Voice\production-local\comfyui-docker\runtime-receipts\codex-comfyui-blender-original-20261027\` (SKILL.md sha256 starts `bafc094f`, full list in the `.sha256.txt` beside it). Edit here, never in the Codex root. Every section below carries an **Applies to** label: `shared`, `jenniejoy_cartoon_3d only`, `newtecons_live_action only` or `aec only`. Read [Domain routing](#domain-routing) first: Blender is shared infrastructure, but cast, prompts, workflows, recipes, anchors and acceptance never cross domains. Game pipelines are not one of the three domains: that content is kept but marked out of scope until a user decision.

**Applies to: shared (all domains).** Blender quản lý hình học, camera, tư thế và trình tự; ComfyUI xử lý ảnh/video theo workflow đã kiểm tra. Tách bạch ba thành phần: MCP `blender`, MCP `comfyui`, và bộ add-on/custom node `alexisrolland/ComfyUI-Blender`. Hai MCP kết nối được không chứng minh bộ add-on đã cài hoặc hoạt động.

## Chọn ngữ cảnh

- **[shared machine facts; its JennieJoy sections = jenniejoy_cartoon_3d only]** Đọc [môi trường cá nhân](references/local-profile.md) khi làm trên máy Admin hoặc dự án JennieJoy Kids. Các phiên bản, model và trạng thái ở đó là bản ghi có ngày, cần kiểm tra lại trước khi chạy.
- **[jenniejoy_cartoon_3d only]** Phim hoạt hình, nhân vật tham chiếu, storyboard: đọc [animation](references/animation.md).
- **[jenniejoy_cartoon_3d only: character GLB/rig/Action, props, sets. The game parts (LOD, collider, engine export) are OUT OF SCOPE until a user decision; game is not a domain]** Nhân vật dùng lại, đạo cụ, vật thể, bối cảnh hoặc asset game: đọc [asset mô-đun và pipeline game](references/reusable-assets-and-game.md). Dùng [manifest asset](assets/reusable-asset.template.json) để lưu phiên bản, dependency, module, LOD/collider và kiểm nhập lại. ~~Nhân vật có thể dùng thêm create-reusable-character (đường dẫn gốc ../create-reusable-character/SKILL.md)~~ (sửa 2026-10-27: skill `create-reusable-character` chỉ có trong Codex, không thuộc workspace này; nếu thiếu, dùng thư viện nhân vật của chính phim); vật thể tĩnh không cần rig mặt hay mô tả người.
- **[shared; the brief's `domain` selects the rules]** Bố cục không gian (rào, vùng, số lượng, tư thế ngồi/quỳ, khung camera) cần kiểm được bằng máy: dùng [Spatial structure API](#spatial-structure-api) (`scripts/scene_layout.py`).
- **[aec only]** Render kiến trúc, kết cấu, MEP, biện pháp thi công: đọc [AEC](references/aec.md). Không mang quy định trang phục, phụ đề hay logo JennieJoy sang AEC.
- **[shared]** Cài đặt, nhập API workflow, lỗi render và đối chiếu upstream: đọc [bridge và đánh giá mã nguồn](references/bridge-review.md).
- **[shared; set `production_domain` first]** Sao chép [mẫu brief](assets/project-brief.template.json) vào thư mục dự án khi cần giao tiếp dữ liệu giữa các bước. Đây là brief, không phải ComfyUI workflow có thể chạy.

## Kiểm tra trước khi thực thi

**Applies to: shared (all domains); every step below is read-only infrastructure checking.**

1. Gọi MCP `blender.get_addon_status`, `blender.get_scene_info` và `comfyui.server_info`. Đối chiếu endpoint với yêu cầu; không tự chuyển sang máy khác.
2. Qua `blender.execute_blender_code`, chỉ đọc `bpy.context.preferences.addons` để kiểm tra `comfyui_blender`; đọc `bl_info.version` từ module đã nạp nếu có. Không import add-on lạ chỉ để kiểm tra.
3. Gọi `comfyui.nodes(action="list", category="blender")`; nếu cần đọc schema bằng `nodes(action="get", name="BlenderInputLoadImage")`. `close_match: true` chỉ là gợi ý, không phải node đã tìm thấy.
4. Dùng `comfyui.system_stats` trước công việc GPU. Dùng `search_models()` rồi `search_models(folder=...)` cho các nhóm workflow thực sự cần. Tên có trên đĩa chưa chứng minh model tải/inference được.
5. Khi thiếu bridge, báo đúng thành phần thiếu. Có thể chuẩn bị hoặc dùng luồng file qua hai MCP: Blender render ra PNG/EXR, ComfyUI `upload_file`, workflow chuẩn dùng `LoadImage`/`SaveImage`, rồi lấy kết quả. Luồng này không tạo panel ComfyUI trong Blender và vẫn cần model phù hợp.

**[shared]** Tool ở trên là tên ngắn theo server; dùng schema công cụ hiện có, không đoán tham số. Ví dụ `nodes(action="search", query="KSampler")` không nhận `limit`; `limit` chỉ dùng cho upstream/downstream. Không gọi generation để thử kết nối.

## Từ brief đến bản thử

**Applies to: shared steps; items tagged for one domain apply only there.**

1. **[shared]** Xác định domain, ảnh tĩnh hay video, nguồn scene/BIM/nhân vật, camera, giới hạn được thay đổi, phong cách và đầu ra. Dùng thông tin đã có; chỉ hỏi phần còn thiếu ảnh hưởng trực tiếp đến kết quả.
2. **[shared; "phim" = jenniejoy_cartoon_3d only (shot with characters, dialogue); AEC = aec only; newtecons_live_action = previz proxies only, no characters]** Ghi `source_scene`, phiên bản model/BIM, đơn vị, frame/FPS, camera và các reference. Với phim, shot phải có mô tả nhân vật, hành động, thoại và continuity. Với AEC, view phải có discipline, element IDs và trạng thái thi công khi liên quan.
3. **[shared]** Dựng hoặc xuất beauty/depth/lineart/mask từ cùng camera, frame, kích thước và crop. Ghi quy ước depth/mask theo schema node; không giả định mọi ControlNet hiểu cùng định dạng. Lưu raw depth/normal dạng dữ liệu tuyến tính nếu cần đo hoặc tái sử dụng.
4. **[shared; workflows are never shared across domains]** Chọn workflow theo model/node thực có. Đọc schema loader/control rồi bind đúng model; không thay model ảnh vào workflow video hoặc ngược lại. Nhập add-on cần API JSON; giữ cả bản editor JSON gốc nếu có.
5. **[shared]** Chuẩn bị bản sao workflow và, khi cần render thử, scene/file làm việc riêng. Nếu scene chưa lưu, không tự ghi đè hay chuyển file gốc. Kiểm tra `validate_workflow(workflow_path=...)`; xử lý node/model thiếu trước khi submit.
6. **[shared]** Khi đã được yêu cầu tạo đầu ra, thử một ảnh hoặc một đoạn đại diện với cấu hình nhỏ mà model hỗ trợ. Đo thời gian/VRAM và xem ảnh/frame thực trước khi mở rộng. ~~Trên RTX 5070 12 GB, dùng từng job; không hứa video/4K dựa riêng vào dung lượng GPU.~~ (sửa 2026-10-27:) Máy hiện là RTX 5080 16 GB, một GPU dùng chung với ComfyUI/VoiceStudio: dùng từng job, kiểm `/queue` trước; không hứa video/4K dựa riêng vào dung lượng GPU, đo từng cấu hình.
7. **[shared]** Với job dài dùng `run_workflow(wait=False)`, lưu `prompt_id`, theo dõi bằng `job`, lấy file bằng `fetch_outputs`. Kiểm tra job/output đã có trước khi retry để tránh sinh trùng.

## Sửa và mở rộng từng phần

**Applies to: jenniejoy_cartoon_3d only (character GLB/rig/Action, props, sets). LOD/collider/runtime items inside are the game pipeline: OUT OF SCOPE until a user decision. Not for newtecons_live_action people (previz proxies only) and not for aec model renders.**

Lưu riêng source geometry, cleanup/retopology, UV/material, rig/weights/shape keys,
module ngoại hình, Action, LOD/collider, render từng shot và hậu kỳ. Mỗi stage ghi
input hash/settings, output thật/hash và phạm vi QA. Đổi tóc/áo/vật liệu chỉ dựng
module và output phụ thuộc khi contract còn đúng; topology đổi phải kiểm lại
weights/shape keys, skeleton đổi phải kiểm lại skinning/Actions. Caption/nhạc/SFX
không kích hoạt Blender hay H3. Với ComfyUI `--cache-none`, tạo graph phụ đọc
GLB/ảnh/video đã lưu bằng node thật có sẵn; nối node vào graph sinh hình học/video
cũ có thể chạy lại toàn bộ upstream. Không tự đổi launch flags để giữ cache.

**[jenniejoy_cartoon_3d only; collider/runtime = game, out of scope]** Đọc mục [hai đường vào và script tự động](references/reusable-assets-and-game.md#hai-đường-vào-comfyui-và-script-tự-động)
khi nối ảnh render và GLB/BLEND. Lưu hai loại receipt riêng; node trả path không
phải mesh loader. Vật dụng từ vựng phải có mesh, render và recipe tham số dùng lại.
Thay surface/pivot/scale phải kiểm lại collider và runtime phụ thuộc.

**[jenniejoy_cartoon_3d only]** Một GLB Hunyuan có thể là lưới tam giác gộp rất nặng, có mảng nền dưới chân,
không UV/texture/rig. Kiểm front/profile/back, tay/mắt và silhouette trước khi
gắn rig; lưu source bất biến. Proxy Decimate là bản thử hiệu năng, không thay
retopology hoạt hình. So chi tiết mặt/ngón tay trước và sau giảm lưới; nếu mất
chi tiết, giữ proxy ẩn và dùng source để kiểm hình. Xem bài học đã đo tại
[hồ sơ môi trường](references/local-profile.md#bài-học-mesh-và-proxy-2026-10-18).

## Bàn giao ảnh render sang hậu kỳ

**Applies to: shared for the receipt principle (separate geometry and render receipts, bind hashes); the film/caption/SFX wording is jenniejoy_cartoon_3d only.**

Bộ geometry và bộ render ảnh cần receipt riêng. Khi renderer phim dùng PNG từ Blender, bind ảnh/hash đúng vật dụng/shot/thẻ vào manifest của bộ dựng; xem gallery chưa chứng minh phim đã dùng ảnh. Thiếu hoặc đổi nguồn phải báo lỗi, kiểm frame trong phim xuất thật. Chỉnh caption/SFX chỉ hậu kỳ. ~~Trên máy Admin sắp đổi5070→5080, đọc mục GPU trong [local profile](references/local-profile.md); giữ venv/model và kiểm runtime trước khi đổi CUDA hoặc batch.~~ (sửa 2026-10-27: việc đổi 5070→5080 đã xong, ghi nhận 2026-10-18, xác nhận lại 2026-10-27; vẫn giữ venv/model và kiểm runtime trước khi đổi CUDA hoặc batch.)

## Giữ nguồn và chứng minh kết quả

**Applies to: shared (all domains); each bullet below is domain-neutral.**

- **[shared]** Yêu cầu kiểm tra kết nối hoặc đọc scene chỉ cho phép thao tác đọc. Không đổi camera, frame, selection, compositor, workflow, model hoặc kích hoạt add-on trong các tác vụ này.
- **[shared]** Với công việc dựng/render đã được yêu cầu, thao tác trên bản sao; lưu đầu ra theo take mới. Trước khi dùng operator render upstream, đọc rủi ro compositor/ViewLayer trong bridge review. Không sửa cấu hình hệ thống, mở cổng LAN hoặc cài node/model chỉ để hoàn tất một cuộc kiểm tra.
- **[shared]** Chỉ cài third-party add-on/nodes khi việc cài đặt thuộc yêu cầu đã được cho phép; giữ nguyên yêu cầu xác nhận riêng mà tool cài node hoặc paid API đặt ra. Không suy quyền cài đặt từ việc đọc repo hoặc tạo skill.
- **[shared]** Lưu manifest tối thiểu: nguồn và hash nếu lấy được, workflow/API JSON, model filenames, tham số/seed, camera/frame, reference bindings, job ID, output thực tế và QA. Đánh dấu `planned`, `validated`, `rendered`, `reviewed` đúng chứng cứ; không gọi workflow chuẩn bị sẵn là phim đã hoàn thành.
- **[shared]** Báo ngắn gọn: hai MCP, bridge, model cần thiết, việc đã làm và phần chưa kiểm thử. Phân biệt model hiện có, capability upstream và capability đã chạy thành công tại máy.

## Domain routing

**Applies to: shared (it defines the split).** Shared infrastructure only (updated 2026-10-27). Blender, the `blender`/`comfyui` MCPs, the file-flow route and `scripts/scene_layout.py` are shared across three production domains. **Cast, prompts, workflows, recipes, anchors, error-db entries and acceptance are never shared.** Every brief names exactly one `domain`; `scene_layout.py validate` rejects cross-domain vocabulary (`DOMAIN_LEAK`), cast bindings in non-cartoon domains (`DOMAIN_CAST`) and wrong statuses.

| Domain | `domain` value | What Blender is for here | What Blender must NOT do here | Owner skill / acceptance |
|---|---|---|---|---|
| **JennieJoyKids** (3D cartoon, *Milk and Mom* and later episodes) | `jenniejoy_cartoon_3d` | Geometry, camera, contact and occlusion **guides for the storyboard** and, beyond layout, the film's own **character GLB/rig/Action and props** (see `references/animation.md`, `references/reusable-assets-and-game.md`, labelled jenniejoy_cartoon_3d only): closed enclosures, animal counts, seated/kneeling planes, five depth planes (near foreground, acting, barrier, farm, far), measured contact points, optional depth/line/mask passes from the same camera. A graybox beauty pass is a control image, never storyboard art. Actors are blocking proxies; identities come from the film's own approved library. | Replace or restyle approved cast; ship a graybox as a storyboard frame; use NEWTECONS/live-action nodes, wardrobe or workflows. | [create-video-jenniejoykids](../create-video-jenniejoykids/SKILL.md), its `references/blender-storyboard-control.md` and `error-db/spatial-blocking-fence-cow-geometry-failure.json`. A guide proves guide geometry only; the generated frame is reviewed separately. |
| **NEWTECONS** (live-action) | `newtecons_live_action` | **Set, blocking and camera previz only**: room/site layout, where bodies stand or sit, lens/height/target, framing of every proxy. Output is a reference image + positions JSON for the live-action unit and for local-ComfyUI anchor planning. | **Never character generation**: no faces, bodies, wardrobe, identity or lip-sync from Blender; no cartoon cast, props or recipes; previz is not an approved anchor or wardrobe reference. | [create-video-newtecons-comfyui](../create-video-newtecons-comfyui/SKILL.md): characters, wardrobe and video stay on local ComfyUI (RTX 5080) with the film's own saved workflows and hash-bound QA. |
| **AEC** (architecture / structure / MEP / construction) | `aec` | **Model renders**: beauty/depth/lineart/mask from the supplied Blender/BIM scene, 4D visibility steps, view framing. See [AEC](references/aec.md). `scene_layout.py` is only for a simplified blockout to check a camera/view, never a substitute for the model. | Invent structure, fittings or supports as approved design; measure or check clearance from generated images; import JennieJoy/NEWTECONS characters, wardrobe, subtitles or logos. | The project's own model, revision and element-ID mapping; labelled `concept` / `model-based illustration` unless the project says otherwise. |

**Game is not a domain.** The game-pipeline content kept in `references/reusable-assets-and-game.md` (LOD, collider, engine export, runtime budgets) is out of scope until a user decision.

References and templates carry an `Applies to:` line; read only those matching the current domain. The archived pre-sync Codex original keeps the older wording (for example "preschool 2D", RTX 5070): those lines are legacy; the corrected originals are struck through with the 2026-10-27 correction beside them.

## Live ComfyUI bridge status (root-verified 2026-10-27)

Applies to: shared infrastructure, all domains.

- ComfyUI runs in Docker (`Comfyui-Studio`, `production-local/comfyui-docker/compose.yaml`) with `--disable-all-custom-nodes --whitelist-custom-nodes comfyui-krea2edit newtecons_live_preview newtecons_branding`, `--disable-partner-nodes` and a read-only `../ComfyUI` mount.
- `production-local/ComfyUI/custom_nodes/ComfyUI-Blender` (19 `Blender*` node classes, no pip dependencies) and `jennie_blender_renderer` exist on disk but are **not whitelisted**, so `/object_info` lists no Blender nodes and `comfyui.nodes(action="list", category="blender")` returns nothing. **The ComfyUI-Blender bridge is not active.** Statements such as "upstream 19 nodes loaded" in `references/local-profile.md` are the 2026-10-18 snapshot and are historical.
- `jennie_blender_renderer/config.json` points at the host path `C:/Program Files/Blender Foundation/Blender 5.2/blender.exe`, which does not exist inside the Linux container, and a render launched from the container would also be a second CUDA user. It cannot work in the container as configured; treat it as host-side only.
- Blender 5.2.2 LTS is installed (`C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`); `blender --background --python ...` works. The Blender MCP (`mcp__blender__*`) was not probed because Blender was not running; check `get_addon_status` only when Blender is already open.
- **Working route today (no bridge):** Blender (CLI or MCP) writes PNG/EXR + JSON, then ComfyUI `LoadImage` through the film's own guarded submit path, then receipts. This is what `scripts/scene_layout.py` feeds.
- **To enable the bridge (a user decision, only after the running 4K SeedVR2 job):** whitelist `ComfyUI-Blender` in the compose `command` (not `jennie_blender_renderer`), recreate the container with an empty queue, then verify `/object_info` for the `Blender*` classes and run the minimal `BlenderInputLoadImage` -> `BlenderOutputSaveImage` graph from [bridge-review](references/bridge-review.md). Nothing was changed by this port.

## Spatial structure API

Applies to: all three domains; the brief's `domain` field selects the rules. Files: `scripts/scene_layout.py` (CLI + validator), `scripts/bpy_layout_template.py` (what `emit-bpy` expands), `scripts/scene_common.py` / `scene_set.py` / `scene_track.py` / `scene_continuity.py` / `scene_placement.py` (shared SET, continuity, placement text; all pure stdlib, imported by `scene_layout.py`), `assets/scene-layout.schema.json`, `assets/examples/`, `scripts/test_scene_layout.py`, `scripts/test_scene_continuity.py`.

```text
python scripts/scene_layout.py validate <brief.json> [--json]           # pure stdlib; exit 0 valid / 1 invalid / 2 usage
python scripts/scene_layout.py emit-bpy <brief.json> <out.py> [--force]  # refuses invalid briefs and silent overwrites
python scripts/scene_layout.py continuity <briefA.json> <briefB.json> [--transition dissolve|wipe|bloom|whip|cut] [--json]  # exit 0 AGREE / 1 MISMATCH or transition refused / 2 usage
python scripts/scene_layout.py placement-text <brief.json> [--ids A,B] [--include-set] [--json]   # deterministic placement sentences for H3 prompts
blender --background --factory-startup --python-exit-code 1 --python <out.py> -- --out-dir <dir> [--width W --height H] [--no-render] [--force]
```

The brief's `domain` field is the same taxonomy as `production_domain` in the templates (one enum, three values; `scene-layout.schema.json` is the validator's source). Conventions: metres; +X right, +Y into the scene, +Z up; `facing_deg` counter-clockwise from +X (90 = +Y, -90 = towards a camera at -Y). A brief holds `domain`, `status`, `ground.zones`, `fences` (closed rectangle with `front_edge`), `props` (box/cylinder/ellipsoid), `actors` (role, pose standing/seated/kneeling, position, facing, `head_top_z`, zone, optional `support` plane), `animals` (species, `count`, members), `camera` (`position_xy`, `height_m`, `target`, `lens_mm`, `sensor_width_mm`), `output` size and `rules`.

What `validate` checks (error codes): schema (`SCHEMA`); unique ids; `COUNT_MISMATCH` (declared count vs members) and `RULE_COUNT` (`exact_count`, e.g. exactly two cows); entity footprints inside their declared zone (`NOT_IN_ZONE`); `NOT_BEHIND_FENCE` / `INSIDE_FENCE` (footprint wholly inside the fence rectangle inset by half thickness + clearance, or wholly outside it); pose planes (`POSE_PLANE` head height above its support, `SEATED_NO_SUPPORT`, `SUPPORT_TOP` / `SUPPORT_XY` when `support.prop_id` names a prop whose top or footprint disagrees); camera framing from the projection math (`CAMERA_CROP`, `CAMERA_BEHIND`; all actors are always checked, `camera_frames` rules add animals and margins); domain isolation (`DOMAIN_*`). The report lists NDC extents per entity. The projection matches Blender's `world_to_camera_view` (checked: identical to 4 decimals on the S01_A example).

What `emit-bpy` builds: zone slabs, fence posts + rails, props, proxy actors/animals (a white marker shows facing), the camera, a saved `.blend`, a **Workbench** guide PNG and `<basename>-positions.json` (world bbox, centre and NDC per entity, hashes, and the brief's rules re-asserted against the geometry actually built; exit code 3 if one fails). The script hard-codes `BLENDER_WORKBENCH`: no Cycles, no Eevee. It refuses to overwrite existing outputs (save a new version, as the v012 layout did).

GPU caution (shared RTX 5080 16 GB): a Workbench render still opens a GPU context. Check `nvidia-smi` free VRAM and the ComfyUI `/queue` first (a 4K SeedVR2 job can sit at about 15.8 of 16.3 GB) and prefer `--no-render` to measure positions and assertions with no GPU use at all. Keep review resolution tiny while another heavy job runs.

Honest scope: the guide proves **guide geometry and framing only**. It does not validate cartoon styling, identity, generated enclosure topology, motion or visual acceptance; a diffusion output must be reviewed pixel by pixel. Footprints and heights are conservative proxy boxes; cows use the v012 proxy numbers (`SPECIES_DEFAULTS`); other species must declare footprint and `height_m`.

Examples (both validate clean): `assets/examples/scene-layout.example.ep04-S01_A.cartoon.json` (domain `jenniejoy_cartoon_3d`; reproduces episode-04 S01_A v012: closed pen, exactly two cows wholly behind the front fence, kneeling/seated planes tied to cushion/bench/stool props) and `assets/examples/scene-layout.example.live-action-previz.json` (domain `newtecons_live_action`, status `previz_only`, four gray blocking proxies, no cast).

Tests: `python -m pytest -p no:cacheprovider --basetemp <dir> scripts/test_scene_layout.py scripts/test_scene_continuity.py` (36 + 36 collected, 1 skipped unless `SCENE_LAYOUT_RUN_BLENDER=1`, which adds a no-render Blender smoke test; the earlier "31 tests" figure was stale).

### Shot continuity

Why (ep04 *Milk and Mom*, review cuts v005-v007, error-db `transition-duplicates-from-shot-continuity-mismatch`): shots generated separately placed characters and props differently, so every transition that showed two shots at once duplicated content (two mothers, two bottles, two Alices). Lock the layout at storyboard time, then choose the transition type from measured agreement. **Applies to: shared tooling; each brief names one `domain` and continuity across two different domains is refused (`DOMAIN_MISMATCH`, exit 2). `newtecons_live_action` previz stays proxies-only with no cast; sets cannot carry actors, animals, cameras or `cast_ref`.**

1. **Shared SET.** A set file (`"kind": "scene_set"`, `$defs/scene_set`; example `assets/examples/scene-set.example.ep04-garden.json`) holds ground zones, fences and static props only. Each shot brief says `"set": "<path.json>"` (relative to the brief's folder) or `"set": "<set_id>"` (looked up among `*.json` next to the brief) and adds only its own camera, actors and moving props. Zones/fences/props of the set are merged into the shot (`ground` becomes optional when a set supplies it; neither -> `GROUND_MISSING`). A shot that redefines a set item with different values gets `SET_MISMATCH` (the message names the fields); others: `SET_NOT_FOUND`, `SET_AMBIGUOUS`, `SET_INVALID`, `SET_DOMAIN`. Set content goes through the same `DOMAIN_LEAK` check. `emit-bpy` builds the merged scene.
2. **`continuity A B`.** Entities are matched by `id` (override with `track_as` when the same thing has different ids). For each shared entity the report gives world displacement (m), facing change (deg, wrapped; props use `yaw_deg`), pose change, the NDC box in **each shot's own camera**, the NDC centre shift and the IoU when both boxes are composited at the same screen place. **AGREE** = every shared entity is within tolerance; **MISMATCH** = offenders listed. Defaults (`POLICY/GUESS, NOT MEASURED`, all inclusive `<=`): 0.15 m, 15 deg, NDC centre shift 0.05 (Euclidean, frame is -1..1), `min_iou` 0 (off), static set props excluded (`include_set_props`, because `SET_MISMATCH` already pins them in the world). Override in a brief's `continuity` block; when both briefs declare a value the stricter one wins. A camera move counts: the same world layout seen from a different camera puts the entity at a different screen place and a dissolve would show it twice. Entities visible in only one shot (`only_in_a` / `only_in_b`, or off-frame in one camera) are reported, never offenders.
3. **`allowed_transitions`.** AGREE -> `dissolve, wipe, bloom, whip, cut`. MISMATCH -> `bloom, whip, cut` only (nothing that shows both shots at once). `--transition X` not in that list -> error code `TRANSITION_NOT_ALLOWED` and exit 1. `wipe_mask_origin` gives the screen point (NDC, plus a region word) farthest from the shared entities (AGREE) or from the offenders (MISMATCH: `usable: false`, hint only). Refusals with exit 2: `BRIEF_INVALID`, `DOMAIN_MISMATCH`, `ASPECT_MISMATCH` (NDC is not comparable across aspect ratios).
4. **`placement-text brief`.** One short deterministic sentence per entity (actors, animals, then shot props, each sorted by id; set props only with `--include-set`; `--ids` filters), e.g. `Mother seated on the bench, lower centre-right, facing screen left` and `sealed milk bottle on the garden table, lower centre-right`. Names come from `label` (parenthesised notes dropped) else the id; "on the X" comes from `support.prop_id` or from a prop resting within 3 cm on another prop's top; screen words are camera-relative bands of the NDC box centre. Paste the same lines into **both** shots' H3 prompts so the generator is told the same placement twice. A locked pair produces identical lines for unmoved entities.

Examples: `scene-layout.example.ep04-S03_B.cartoon.json` -> `...S04_A-mismatch.cartoon.json` (bottle and Cup B moved, Mother repositioned and turned: MISMATCH, exit 1, allowed `bloom, whip, cut`) and -> `...S04_A-locked.cartoon.json` (everything within tolerance, small push-in: AGREE, exit 0). All numbers in them are an invented illustration derived from the S01_A example, not the real S03_B/S04_A coordinates.

**Honest scope:** `continuity` proves that the **planned layouts** agree (or not) within the stated tolerances and picks a safe transition from that. It does **not** prove the generated H3 frames obey the layout, and it cannot see content that is not in the brief (extra characters, background drift, props the brief omits). The review still checks full-resolution pixels at every transition frame; `AGREE` is permission to try a simultaneous-two-shot transition, not a pass.

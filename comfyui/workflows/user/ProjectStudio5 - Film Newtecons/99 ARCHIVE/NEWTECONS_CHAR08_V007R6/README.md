# N70 ? CHAR08 V007R6 Krea2 edit

Tr?ng th?i: BLOCKED_SOURCE_GRAPH_MISMATCH ? ch?a t?o hai API graph; ch?a submit, ch?y GPU ho?c g?i validate_prompt.

User ?? duy?t theo Task N70 ng?y 2026-10-30. Kh?ng c?n duy?t l?i ?nh; v??ng m?c l? y?u c?u gi? c?u tr?c node kh?ng ph? h?p v?i graph ngu?n th?c t?.

## B?ng ch?ng ngu?n

- Graph V007R5: `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\user\default\workflows\NEWTECONS_CHAR08_V007\CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R5_LOGO_ONLY.api.json`; SHA-256 `5db96621d4ae`.
- C? 18 node; ch? gh?p mi?ng/logo, crop v? l?u ?nh. Kh?ng c? prompt encoder, loader Krea2, sampler ho?c latent.
- Node classes: ImageCompositeMasked, ImageCrop, ImageScale, LoadImage, LoadImageMask, MaskToImage, NewteconsLocalMarkRemoval, NewteconsPerspectiveComposite, PreviewImage, SaveImage.
- Graph Krea2 c? s?n ? V007R4: `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\user\default\workflows\NEWTECONS_CHAR08_V007\CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R4.api.json`; SHA-256 `11029118ad7a`.
- V007R4 s?a mi?ng b?ng mask ri?ng v? LoRA head-swap. Kh?ng th? d?ng nguy?n mask mi?ng/LoRA ?? ?? cam k?t s?a m?, c? ?o v? th?t l?ng.
- Prompt ngu?n: `J:\1.JennieHomeSchool\03 Voice\docs\plans\2026-10-30-newtecons-10lan\reports\N64.md`; SHA-256 `aa6a69a8980b`.
- N64 c?ng x?c nh?n V007R5 kh?ng ch?y Krea2. Negative string ch? d?ng khi graph c? tr??ng negative-text th?t; ConditioningZeroOut kh?ng ??c chu?i negative.

## ?nh ??u v?o d? ki?n / tham chi?u N64

C?c hash d??i ??y ???c t?nh tr?c ti?p t? file tr?n ??a. Ch?a c? graph V007R6 n?n ch?a c? ?nh n?o ???c n?i v?o graph m?i.

| Vai tr? | ???ng d?n | SHA-256 (12) | K?ch th??c |
|---|---|---|---|
| FULLBODY | `J:\1.JennieHomeSchool\03 Voice\production-local\JennieJoyKids-Story\Newtecons-TienDo-KichTinh-30s\casting\CHAR_08_Tran_Thao_Mai\gpt\v001\images\CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R5_FULLBODY_CANDIDATE_00002_.png` | `6bde79736d45` | 1536?2048 |
| PORTRAIT | `J:\1.JennieHomeSchool\03 Voice\production-local\JennieJoyKids-Story\Newtecons-TienDo-KichTinh-30s\casting\CHAR_08_Tran_Thao_Mai\gpt\v001\images\CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R5_PORTRAIT_CANDIDATE_00002_.png` | `8859618cca83` | 768?1152 |
| face anchor người dùng đã duyệt | `J:\1.JennieHomeSchool\03 Voice\production-local\JennieJoyKids-Story\Newtecons-TienDo-KichTinh-30s\casting\CHAR_08_Tran_Thao_Mai\references\CHAR_08_FACE_ANCHOR_USER_APPROVED_c921dfea.png` | `e98503e94062` | 1252?1702 |
| ảnh lưới mịn và dấu cổ áo đã duyệt | `J:\1.JennieHomeSchool\03 Voice\production-local\character-library\newtecons\wardrobe\v001\user-feedback\SHIRT_APPROVED_FINE_GRID_COLLAR_LOGO_REFERENCE.png` | `55f0a34b4777` | 550?912 |
| nguồn áo gốc | `J:\1.JennieHomeSchool\03 Voice\production-local\character-library\newtecons\wardrobe\v001\originals\ÁO PHẢN TRONG.png` | `59aba9523b61` | 1920?2560 |
| ảnh mũ candidate002 | `J:\1.JennieHomeSchool\03 Voice\production-local\character-library\newtecons\wardrobe\v001\assets\NT_HELMET_WHITE_V001_FRONT_candidate002.png` | `b9ad43152567` | 768?768 |
| ảnh mũ gốc | `J:\1.JennieHomeSchool\03 Voice\production-local\character-library\newtecons\wardrobe\v001\originals\UNIFORM_HELMET.png` | `deae83d60abb` | 132?81 |
| logo NEWTECONS màu chính thức | `J:\1.JennieHomeSchool\03 Voice\production-local\character-library\newtecons\wardrobe\v001\originals\LOGO_NEWTECONS_COLOR.png` | `e320eabbf4af` | 1134?633 |
| N navy | `J:\1.JennieHomeSchool\03 Voice\production-local\character-library\newtecons\wardrobe\v001\assets\NEWTECONS_N_COLLAR_NAVY_V001.png` | `fc04aee0e45f` | 341?391 |

## Prompt Krea2 ? PORTRAIT (nguy?n v?n N64)

```text
Use the supplied CHAR_08 V007R5 portrait as the image to edit. This is a local Krea2 reference edit. Treat the portrait as the locked base plate for identity, face, expression, gaze, head angle, pose, hands, body proportions, crop, office background, perspective and lighting. Use the approved face anchor only for identity confirmation. Preserve the exact facial structure and proportions, eyes, eyebrows, nose, lips, jawline, age, skin tone, natural pores, thin silver round glasses, dark-brown ponytail and hairline. Strict identity preservation: no face blending, reconstruction, beautification or smoothing. Keep the expression and pose unchanged. Preserve all unmasked pixels.

Edit only the masked wardrobe areas. Preserve the tailored shirt’s very fine dense blue-white woven microgrid, folds and fit, and preserve the dark navy-black trousers. Add the plain black belt specified by CHAR_08 r005 through the existing trouser loops, with a discreet simple dark buckle.

Add a clean white safety helmet worn securely on her head, aligned to the existing head angle and perspective. Match the supplied helmet source: red N above navy NEWTECONS wordmark, centered on the front shell just above the brim. Use the official color mark as the exact artwork reference; preserve its colors, proportions and position. Keep the shell mark flat against the curved helmet surface.

On the shirt, reproduce only the tiny navy N embroidery at the same collar tip, image-side and scale as the approved shirt reference. Integrate fine thread stitches into the cotton weave; follow the collar plane, folds and light. It must look embroidered into the fabric, not like an adhesive sticker or raised patch. Keep the chest pocket plain; do not add a separate chest mark.

Keep the current portrait canvas and crop; do not zoom out to reveal more of the body. Preserve the office and all non-target areas. Return one image.

NEGATIVE (only if the graph exposes a separate negative-text input): face drift; facial reconstruction; beautification; skin smoothing; changed glasses; changed expression; changed hairline or ponytail; changed pose; altered body proportions; extra fingers; malformed hands; reframing; broad gingham; redesigned shirt; added vest; lanyard or badges; extra chest mark; duplicate hardhat; rigid raised patch edge; adhesive halo; plastic skin; blur; artifacts; altered office background; extra props.
```

## Prompt Krea2 ? FULLBODY (nguy?n v?n N64)

```text
Use the supplied CHAR_08 V007R5 fullbody image as the image to edit. This is a local Krea2 reference edit. Treat the fullbody image as the locked base plate for identity, face, expression, gaze, head angle, stance, arms, hands, body proportions, framing, office background, perspective and lighting. Use the approved face anchor only for identity confirmation. Preserve the exact facial structure and proportions, eyes, eyebrows, nose, lips, jawline, age, skin tone, natural pores, thin silver round glasses, dark-brown ponytail and hairline. Strict identity preservation: no face blending, reconstruction, beautification or smoothing. Keep the expression and pose unchanged. Preserve all unmasked pixels.

Edit only the masked wardrobe areas. Preserve the tailored shirt’s very fine dense blue-white woven microgrid, folds and fit, and preserve the dark navy-black trousers. Add the plain black belt specified by CHAR_08 r005 through the existing trouser loops, with a discreet simple dark buckle.

Add a clean white safety helmet worn securely on her head, aligned to the existing head angle and perspective. Match the supplied helmet source: red N above navy NEWTECONS wordmark, centered on the front shell just above the brim. Use the official color mark as the exact artwork reference; preserve its colors, proportions and position. Keep the shell mark flat against the curved helmet surface. Use the helmet already visible on the desk as the appearance guide; do not create a second helmet.

On the shirt, reproduce only the tiny navy N embroidery at the same collar tip, image-side and scale as the approved shirt reference. Integrate fine thread stitches into the cotton weave; follow the collar plane, folds and light. It must look embroidered into the fabric, not like an adhesive sticker or raised patch. Keep the chest pocket plain; do not add a separate chest mark.

Keep the original head-to-shoes framing and both shoes fully visible. Do not alter her stance, office background, camera perspective or lighting. Return one image at the same canvas size.

NEGATIVE (only if the graph exposes a separate negative-text input): face drift; facial reconstruction; beautification; skin smoothing; changed glasses; changed expression; changed hairline or ponytail; changed pose; altered body proportions; extra fingers; malformed hands; cropped feet; reframing; broad gingham; redesigned shirt; added vest; lanyard or badges; extra chest mark; duplicate hardhat; rigid raised patch edge; adhesive halo; plastic skin; blur; artifacts; altered office background; extra props.
```

## B?n giao root

- Quy?t ??nh ?ang ch?: cho ph?p d?ng c?u tr?c Krea2 V007R4 v?i ?nh V007R5 l?m base, ho?c gi? tuy?t ??i c?u tr?c V007R5 v? ghi nh?n b? ch?n.
- N?u chuy?n sang Krea2: c?n mask ??ng m?/c?/th?t l?ng, x? l? m? tr?n b?n ?? kh?ng c? hai m?, b?o v? m?t/da b?ng composite ngo?i mask; gi? canvas c?a t?ng ?nh.
- Kh?ng th? cam k?t th?u/logo/m?u da ch?n th?t b?ng ki?m tra JSON. Root c?n validate graph r?i pilot GPU v? QA ?nh.

## CH? N?O T?I ?O?N ? N?I TH?NG

- Ch?a t? ??i sang c?u tr?c R4 v? Task N70 y?u c?u gi? c?u tr?c R5.
- Theo N64: logo ?o l? N navy nh? th?u ? ??u l? c?, kh?ng th?m logo ng?c; m? d?ng N ?? tr?n ch? NEWTECONS navy.
- Y?u c?u ??i m? tr?c ti?p c?a Task N70 ???c ?u ti?n h?n quy ??nh kh?ng m? trong r005.
- Kh?a th?t l?ng t?i m?u ??n gi?n l? di?n gi?i c?a N64; r005 ch? y?u c?u th?t l?ng ?en tr?n.
- Ch?a c? mask wardrobe ???c ki?m tra v? ch?a c? output V007R6; kh?ng tuy?n b? ch?t l??ng ?nh ?? ??t.


## N71 ? K?t qu? d?ng graph local (2026-10-30)

M?c n?y c?p nh?t tr?ng th?i N70 ph?a tr?n: ?? t?o hai API graph m?i; ch? ki?m tra t?nh v? GET /object_info, ch?a submit ho?c ch?y graph. To?n b? n?i dung README c? ???c gi? nguy?n byte.

| Graph | SHA-256 (12) | S? node |
|---|---|---|
| `NEWTECONS_CHAR08_V007R6_PORTRAIT.json` | `38c44e409027` | 55 |
| `NEWTECONS_CHAR08_V007R6_FULLBODY.json` | `e863ffa97e99` | 58 |

### ?nh ??u v?o th?c s? ?? n?i

M?i graph d?ng ?nh R5 t??ng ?ng ? node 1 l?m base/identity ref, c?ng b?y ?nh tham chi?u ? c?c node 41, 44, 47, 50, 53, 56, 59. Hai graph d?ng t?ng c?ng ch?n ?nh. C?c ???ng d?n ComfyUI b?n d??i tr? t?i b?n sao ?? x?c minh SHA-256 ??y ?? tr?ng ?nh g?c trong b?ng N64 ? tr?n; kh?ng ch?p th?m ?nh.

| Vai tr? | ???ng d?n th?c s? n?p | Gi? tr? LoadImage.image | SHA-256 (12) |
|---|---|---|---|
| FULLBODY | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\output\NEWTECONS\CHAR08\V007\CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R5_FULLBODY_CANDIDATE_00002_.png` | `NEWTECONS/CHAR08/V007/CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R5_FULLBODY_CANDIDATE_00002_.png [output]` | `6bde79736d45` |
| PORTRAIT | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\output\NEWTECONS\CHAR08\V007\CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R5_PORTRAIT_CANDIDATE_00002_.png` | `NEWTECONS/CHAR08/V007/CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R5_PORTRAIT_CANDIDATE_00002_.png [output]` | `8859618cca83` |
| face anchor người dùng đã duyệt | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\input\CHAR_08_FACE_ANCHOR_USER_APPROVED_c921dfea.png` | `CHAR_08_FACE_ANCHOR_USER_APPROVED_c921dfea.png` | `e98503e94062` |
| ảnh lưới mịn và dấu cổ áo đã duyệt | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\input\CHAR_08_55f0a34b4777207a2add.png` | `CHAR_08_55f0a34b4777207a2add.png` | `55f0a34b4777` |
| nguồn áo gốc | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\input\UNIFORM_SHIRT_GINGHAM.png` | `UNIFORM_SHIRT_GINGHAM.png` | `59aba9523b61` |
| ảnh mũ candidate002 | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\output\Newtecons_Wardrobe_v001\NT_HELMET_WHITE_V001_FRONT_00001_.png` | `Newtecons_Wardrobe_v001/NT_HELMET_WHITE_V001_FRONT_00001_.png [output]` | `b9ad43152567` |
| ảnh mũ gốc | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\input\UNIFORM_HELMET.png` | `UNIFORM_HELMET.png` | `deae83d60abb` |
| logo NEWTECONS màu chính thức | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\input\LOGO_NEWTECONS_COLOR.png` | `LOGO_NEWTECONS_COLOR.png` | `e320eabbf4af` |
| N navy | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\input\NEWTECONS_N_COLLAR_NAVY_V001.png` | `NEWTECONS_N_COLLAR_NAVY_V001.png` | `fc04aee0e45f` |

### C?u tr?c v? gi?i h?n

- D?ng loader, VAE, grounded encoder, model patch, inpaint, sampler v? composite t? graph Krea2 R4. Thay crop/mask mi?ng b?ng canvas R5 v? mask ROI m?i. LoRA head-swap ???c thay b?ng `krea2_general_edit_v2.safetensors` ?? c? trong object_info; kh?ng t?i model.
- Gi? seed 2026102604, 12 steps, CFG 1.0, Euler/simple, denoise 1.0 t? R4. D?ng ref_boost 1.0 cho b?ng tham chi?u; grounding_px 1536 ?? t?ng ?? ph?n gi?i ?nh tham chi?u.
- Hai chu?i prompt ???c tr?ch tr?c ti?p t? hai fenced block `text` c?a README c? v? so s?nh b?ng k? t? sau khi ??c l?i JSON. Kh?ng th?m, b? ho?c s?a ch?, k? c? d?ng NEGATIVE c? ?i?u ki?n. R4 d?ng ConditioningZeroOut, kh?ng c? negative-text ri?ng: d?ng NEGATIVE v?n n?m nguy?n v?n trong prompt; kh?ng tuy?n b? ??y l? negative conditioning th?c s?.
- B?ng tham chi?u 1152?1536, ? 384?512, kh?ng ch?n ch?; th? t? t? tr?i sang ph?i, tr?n xu?ng d??i: face anchor, ?o ?? duy?t, ?o g?c, m? candidate002, m? g?c, logo m?u, N navy. Gi? t? l? t?ng ?nh. B?ng ???c n?i v?o image_b/source_image_b/source_latent_b.
- Mask ???c t?o b?ng SolidMask/FeatherMask/MaskComposite local, kh?ng ph? thu?c file mask ngo?i. VAEEncodeForInpaint grow_mask_by=0; ImageCompositeMasked gi? pixel R5 ngo?i mask. PORTRAIT 768?1152, FULLBODY 1536?2048; kh?ng ??i framing.
- ROI NEWTECONS_CHAR08_V007R6_PORTRAIT.json: `(t?n, x, y, r?ng, cao)` = `[["helmet_top", 210, 0, 280, 82], ["helmet_left", 210, 82, 76, 64], ["helmet_right", 449, 82, 41, 64], ["collar", 422, 338, 54, 48], ["belt", 230, 704, 296, 68]]`.
- ROI NEWTECONS_CHAR08_V007R6_FULLBODY.json: `(t?n, x, y, r?ng, cao)` = `[["helmet_top", 594, 0, 280, 82], ["helmet_left", 594, 82, 76, 64], ["helmet_right", 833, 82, 41, 64], ["collar", 806, 338, 54, 48], ["belt", 614, 704, 296, 68], ["remove_desk_helmet", 208, 742, 184, 124]]`.

### Output ki?m tra th?t

```text
GET http://127.0.0.1:8188/object_info -> HTTP 200
SOURCE_IMAGES_SHA256_MATCH=9/9
COMFY_INPUT_OUTPUT_COPIES_FULL_SHA256_MATCH=9/9
{"file": "NEWTECONS_CHAR08_V007R6_PORTRAIT.json", "nodes": 55, "missing_class_types": [], "schema_errors": [], "prompt_exact": true, "local_only": true, "sha256": "38c44e4090278db7772052cc571fd9aee472c3da1414808f8999bcd14f66bace"}
{"file": "NEWTECONS_CHAR08_V007R6_FULLBODY.json", "nodes": 58, "missing_class_types": [], "schema_errors": [], "prompt_exact": true, "local_only": true, "sha256": "e863ffa97e9900298b9ef67a05d1460839d5b49415b290662e49a390dc58c876"}
POST /prompt calls=0; graph executions=0; GPU calls=0
Source R4/R5 graphs unchanged; source hashes verified.
```

Ki?m tra b? sung: input b?t bu?c, t?n input, ki?u li?n k?t, DAG, m?i node c? ???ng t?i output, model/LoRA c? trong danh s?ch object_info v? file ?nh t?n t?i/kh?p hash. ??y kh?ng ph?i ki?m th? th?c thi ho?c x?c nh?n ch?t l??ng ?nh.

### CH? N?O T?I ?O?N ? N?I TH?NG

- T?a ?? mask l? ??c l??ng th? c?ng sau khi xem hai ?nh R5; ch?a ph?i segmentation ???c duy?t. V?ng m? tr?nh m?t b?ng ba ROI; FULLBODY th?m ROI m? tr?n b?n. Kh?ng b?o ??m mask ?? cho m? ho?c lo?i b? m? b?n s?ch.
- Gh?p b?y tham chi?u th?nh m?t b?ng l? l?a ch?n c?a N71 v? node Krea2 hi?n ch? c? image/image_b. Kh? n?ng model hi?u ??ng t?ng ?nh, gi? m?t v? t?i t?o logo/th?u ch?a ???c th?.
- Ch?n General Edit V2 thay head-swap v? ref_boost/grounding m?i ?? ph? h?p ch?nh trang ph?c l? quy?t ??nh d?ng graph, ch?a ph?i tham s? ?? ??t QA. CFG 1.0 k? th?a R4 c? th? y?u khi x?a m? b?n.
- Gi? nguy?n c? d?ng NEGATIVE theo r?ng bu?c nguy?n v?n; kh?ng t? t?ch ho?c vi?t l?i prompt. Kh?ng c? k?t qu? render V007R6 ?? x?c nh?n ch?t l??ng, t?c ?? ho?c m?c VRAM.

# Independent visual audit — Navy Cyan workshop intro

Date: 2026-11-12. Scope: independent visual inspection and bounded temporal sampling. No production assets, code or configuration were edited by this auditor. New files are this report and six PNGs decoded from the delivered MP4.

## Verdict

The inspected deliverable has readable Navy/Cyan composition, correct visible Vietnamese including **TẦM**, intact supplied company artwork, and an observable staged mechanical assembly in the actual encoded video. No major new visual defect was found that prevents handoff as a **2.5D technical/editorial workshop intro**.

The result should not be described as photoreal Iron Man cinema. Its mechanical sequence uses flat isometric illustration, articulated gripper silhouettes, independent part arrival/alignment, small latches, and activation traces. This audit samples the encoded sequence; it does not certify every interpolated frame, audio synchronization, playback smoothness or a physically simulated gripper/part contact model.

## Delivered video independently checked

- File: `exports/workshop-ai-intro-1080p.mp4`.
- SHA-256 measured from the actual file: `42576bf13437c787d89a05fb64ed5c8d9a4c7bf53928d871cb6ea853d66e495b`.
- `ffprobe`: 1920 × 1080, 30/1 fps, 600 frames, 20.000000 seconds.
- FFmpeg decoded six timestamps successfully, each with exit code 0: 5.2, 5.6, 6.0, 6.4, 6.9 and 7.4 seconds. All six PNGs were visually inspected.

| Actual encoded sample | Observed state |
| --- | --- |
| `evidence/decoded-5.2s.png` | Base plate present; frame and services have not yet arrived; four latch markers visible below. |
| `evidence/decoded-5.6s.png` | Frame present; upper duct is being positioned; left articulated gripper reaches the duct location. |
| `evidence/decoded-6.0s.png` | Duct and pipes present; tray is arriving; both grippers are visible, with the right gripper awaiting the next part. |
| `evidence/decoded-6.4s.png` | Tray aligned; control panel is arriving/aligned by the right gripper; left gripper is fading/retracting. |
| `evidence/decoded-6.9s.png` | Full module assembled; right gripper is retracting/fading; small bottom latch details are present. |
| `evidence/decoded-7.4s.png` | Full module held in place; activation trace/scan line has appeared around the panel/base region. |

These ordered observations confirm meaningful temporal progression in the delivered MP4 rather than relying only on separately rendered stills. They establish parts arriving, alignment, gripper withdrawal, and a later activation cue. The tiny latch marks are visually restrained, so a claim of a large, dramatic physical locking action would overstate their screen prominence.

## Updated assembly frames and layout clearance

Freshly inspected `exports/frame-0165.png`, `frame-0185.png`, `frame-0210.png`, `frame-0239.png`, and `portrait-frame-0185.png` after the M07 gripper/latch addition.

- Landscape 0165 shows the frame and left gripper with the upper duct still approaching. Landscape 0185 shows duct, pipes and tray with both articulated arms. Landscape 0210 and 0239 show the completed panel and module with grippers withdrawn.
- The sampled landscape assembly states do not collide with the white field-application headline. The large logo and department line retain their own clear header area.
- Portrait 0185 preserves the full main MEP module and headline. The outer decorative gripper bases/outer circular joints extend beyond the left and right viewport edges and are visibly cropped. This is a bounded edge-composition limitation; it does not crop the central MEP subject or text. The portrait render should not be represented as having every decorative component fully inside the safe area.
- The dominant style remains an isometric technical illustration with clear cyan highlights. It has mechanical storytelling, while lighting, material realism, camera travel, motion blur and physically driven contact are not the visual language of this deliverable.

## Vietnamese and event content

Inspected seven initial landscape states (0000, 0090, 0185, 0210, 0270, 0420, 0599), five portrait states (0000, 0185, 0270, 0420, 0599), and the updated assembly states listed above.

- `frame-0270.png` and `portrait-frame-0270.png` visibly read **THÔNG TIN TRONG TẦM TAY**, with TẦM rather than TẰM.
- The inspected headings **KHỐI CƠ ĐIỆN**, **ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG**, and **ỨNG DỤNG AI CÓ TRÁCH NHIỆM** have intact visible diacritics.
- Final landscape and portrait states visibly read `14.11.2026`, `12A NEWTECONS`, and `08:30 - 11:00` without clipping.
- Navy backgrounds, white headings and cyan accents give strong focal contrast. The opening and closing WORKSHOP/AI word shapes remain inside both canvases.

## Measured portrait text limitation

In the 1080 × 1920 portrait field-application frame, thresholded white text glyph bounds are x = 76–1004, y = 396–460, giving 928 × 64 pixels. At a 360-pixel display width this corresponds to approximately 21 pixels of glyph height. It remains readable, but a one-line long headline is less dominant on small mobile displays than the landscape treatment.

The corresponding landscape heading has measured white glyph bounds x = 127–1633, y = 227–332: 1506 × 105 pixels on 1920 × 1080. These are measured glyph bounds, not nominal font sizes or invented acceptance thresholds.

## Company artwork, placement and microtext

Visually inspected `assets/brand/A02-engineers-branded.png` (1332 × 1181 RGBA), `company-logo-full-color.png` and `company-logo-full-white.png` (both 1134 × 633 RGBA).

- Helmets visibly carry the supplied red N and blue NEWTECONS artwork; vests carry the supplied white treatment. The visible arrangement includes the small rule/tagline treatment rather than a newly typeset substitute.
- The source full-color artwork visibly contains N, NEWTECONS, registered mark, rule and **Build on trust**. The all-white source can appear blank in a white-background viewer; it has nonempty alpha and visibly appears as the intended logo in the navy-vest composite.
- Exact embedded PNG byte identity was independently proven by the package critic, as communicated by the root agent. This report's own finding is visual consistency and correct placement; it does not substitute a visual impression for that separate byte-identity test.
- `brand-placement.json` records helmet logo widths of 150 and 145 pixels and vest widths of 120 and 135 pixels on the 1332-pixel source canvas. The small tagline is therefore microtext before scene downscaling. Source fidelity passes independently of whether every tagline letter is readable in the final composition. Do not promise final-size prose readability for PPE microtext.
- The large company logo in the header is readable in both aspect ratios.

## Alpha/fringe finding

The raw engineer cutout shows minor pale contour noise at close inspection, particularly around helmet/hair contours. In the inspected navy composite `frame-0090.png`, this does not become a broad distracting white matte. This is a bounded residual edge-quality limitation, not a claim of perfect matting.

A connected-component measurement on the A02 alpha channel found zero disconnected components of at least 3 pixels at alpha > 10. At alpha > 128, four tiny disconnected components totalled 17 pixels. This measurement bounds isolated specks; it does not certify every antialiased edge or exclude low-alpha matte contamination.

## Separation for animation handoff

The branded engineer image contains no workshop headline. The package separately supplies mechanical part PNG/SVG pairs and text PNG/SVG pairs T01–T34, with text content and animation manifests. `text-content.json` records the correct T33 phrase separately. This supports independently animating images and text for the Claude handoff.

## Remaining quality limits

1. Mechanical motion is 2.5D editorial assembly; photoreal cinematic armor assembly is outside the observed result.
2. Small latch/activation details are subtle at full-frame scale; the sequence is clearer in the dedicated 3-second segment or when viewed at native 1080p.
3. Portrait decorative gripper bases crop at the side edges in frame 0185; central subject and copy remain intact.
4. PPE tagline microtext is preserved but too small for reliable final-video prose readability.
5. Minor source contour noise remains visible on close inspection; no broad objectionable matte was seen in the inspected navy composite.

No additional production edit is requested by this audit. The limits above should accompany any quality claims made at handoff.

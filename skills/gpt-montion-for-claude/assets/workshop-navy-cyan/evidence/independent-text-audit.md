# Independent text asset audit

Reviewed on 2026-11-12. Scope: `scripts/TextAssetRenderer.cs`, `scripts/render-text.ps1`, `text-content.json`, `text-animation.json`, and the generated PNG/SVG assets. The reviewer did not modify production code or assets. A fresh render was written only to `evidence/text-rerender`.

**Final verdict: APPROVE for the current 34 text assets and their generator.** No unresolved CRITICAL or HIGH findings. The two MEDIUM findings and the timestamp finding from the initial review are resolved. This verdict concerns text assets and their animation bindings; it does not certify the complete video or browser playback.

## Resolved findings

1. **Incomplete canonical coverage — resolved.** `scripts/render-text.ps1:21` verifies the canonical source SHA-256. Lines 27–49 define and check all 34 required asset IDs and strings, including Part 2, opening names/subtitles, event metadata, and intro hooks. Missing IDs, duplicate IDs, and unexpected or changed strings fail before rendering. All 23 canonical section title/presenter/subtitle strings were also independently compared against the manifest and retained exactly.
2. **Unpinned font input — resolved.** `scripts/render-text.ps1:55` pins both exact font files by SHA-256 and records their versions and paths. `scripts/TextAssetRenderer.cs:68` loads the explicit font file into a private collection, avoiding family lookup from the machine-wide registry. Actual production and independent rerender outputs match exactly.
3. **Hardcoded evidence date — resolved.** `scripts/render-text.ps1:80` records `generated_at_utc` from the runtime clock.

## Measured positive checks

- Fresh Windows PowerShell Desktop 5.1.26100.9711 process completed with exit code 0: **34 transparent PNG and 34 outlined SVG assets**, with **34 text contract checks**.
- Independent rerender timestamp: `2026-11-12T02:25:36.0028195Z`.
- **68/68 rerender SHA-256 hashes match production and the production verification report.** Production file hashes were checked directly rather than trusting the report alone.
- **34/34 SVGs** retain matching Unicode title/data-text, top-level asset group, and intact `RUN_01` group.
- **34/34 manifest assets** have matching group/run IDs in `text-animation.json`.
- Minimum distance between any painted pixel and the raster canvas edge is **19 pixels**. All outputs contain transparent pixels, painted pixels, and antialiased pixels; the renderer's alpha-bound checks passed.
- T16 contains the exact word `tầm`: `U+0074 U+1EA7 U+006D`. The reviewer inspected its PNG and confirmed the displayed circumflex/grave mark. No clipping was visible in that inspected asset.
- T14–T18 titles use **Bold 130 px**. T19–T23 presenters use **Italic 90 px**, without Bold. T24 Part 2 presenter uses Italic 90 px.
- Direct character-map inspection of the pinned fonts found **zero missing glyphs** among the **111 distinct Bold characters** and **61 distinct Italic characters** used in the manifest. Both files cover U+1EA7. This provides direct coverage evidence for the current text rather than inferring glyph coverage from the font family name.

## Negative checks

The reviewer executed the current script's pre-render validation prefix in fresh Windows PowerShell, injecting changes into in-memory manifest objects. No production manifest, code, fonts, or assets were changed. Each test failed with the expected message before the directory creation/render stage.

| Test | Expected rejection observed |
| --- | --- |
| Change Part 2 presenter | `Text contract mismatch: T24_PART2_PRESENTER` |
| Remove required T32 asset | `Incomplete text asset set; expected 34.` |
| Duplicate an ID | `Duplicate text asset IDs.` |
| Change canonical hash | `Canonical source hash differs from manifest.` |
| Change Vietnamese T16 text | `Text contract mismatch: T16_TOPIC_3` |
| Request output outside the two allowed directories | `OutputDir must be assets/text or evidence/text-rerender inside this package.` |
| Change expected Bold font hash in memory | `Font version mismatch: Bold ...` |

The PowerShell caller enforces allowed output directories and rejects linked output directory ancestors before writing. C# disposable drawing resources use `using`, and locked bitmap data is released in `finally`. SVG text and attributes are escaped; coordinates use invariant formatting. No swallowed exception was found in the reviewed rendering path.

## Reproduction inputs and limits

| Input | Value |
| --- | --- |
| Bold file | `C:/Windows/Fonts/RobotoCondensed-Bold.ttf` |
| Bold SHA-256 | `32E42D57A7A9E62DD943722D5ECE99AF4736FBD11A9927CF07378299C117D3BD` |
| Italic file | `C:/Windows/Fonts/RobotoCondensed-Italic.ttf` |
| Italic SHA-256 | `776BFB34E9311C23DCB64137EA81FF49056B13CCE7212E4F71870EBE01653E4E` |
| Canonical SHA-256 | `3D720996A234C9A646C223910136BCA351EE0E152F2BD3FCA92AF3839570A018` |
| Reviewed C# SHA-256 | `0D5D212F8B3ACB51B73AE2494348509D76606AC4C409EBFCF005FE7B661CA827` |
| Reviewed PowerShell SHA-256 | `EA8D4888A15AD8B1F06A0D571E0B6E1DD7C12381E5B0A54C3BA22AC40AA287D8` |

PNG/SVG outputs have no runtime font dependency. Regeneration requires Windows PowerShell Desktop 5.1, Windows drawing/WPF assemblies, and the two exact pinned font files installed in the Windows Fonts directory. Same-machine byte reproducibility is measured; no second-machine or cross-OS render was performed. No font source/license file was found in this reviewed package, and no broader license/source search was performed.

Each SVG exposes one intact phrase outline, suitable for phrase-level animation and masks. Separate word/glyph groups are not supplied; per-word choreography requires another verified representation. All text is available as individual assets, while only the manifest's selected main assets belong to the 20-second intro; the other assets have the optional detail template.

`dotnet build` and `dotnet format --verify-no-changes` were attempted during the initial review. Both could not locate a project/solution because this package uses a standalone C# source file rather than a .NET project. Build output: `MSBUILD : error MSB1003: Specify a project or solution file.` The supported PowerShell `Add-Type` compilation and real rendering path completed successfully after the final changes.

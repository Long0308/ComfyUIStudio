# Independent review — 2026-11-12

**Later logo-specific correction, same date:** the approval below covers the recorded technical/content checks. It is not full brand-fidelity approval. A subsequent independent pixel audit found a header clearspace defect in both Navy–Cyan PNGs and could not certify small helmet/vest tagline, ® or exact geometry. The posters have not been repaired. See [logo audit](logo-audit-2026-11-12.md).

The original four-image package and the added navy/cyan style were reviewed by separate code, C# and final-artifact reviewers. Reviewers did not author the files they assessed. Final verdict: **APPROVE within the documented scope**.

## Original selected poster package

- A reviewer ran `verify.ps1 -Render` in a separate output directory under Windows PowerShell 5.1: exit 0, both freshly rendered PNGs byte-identical to the two v2 references.
- Six assets passed hashes, sizes and dimensions; four prompt JSON files passed the required-field checks. Text records: 38 portrait + 39 landscape.
- The packaged `PosterRenderer.cs` is byte-identical to the previously approved renderer. Native `Add-Type` compilation succeeded. This is a standalone renderer, not a project requiring a `.csproj` build.
- Width-fit auditing does not prove vertical glyph clearance. Both actual original PNGs were visually reviewed; no visible text cropping or overlap was identified. Font hashes are informational.

## Navy/cyan addition

- Actual final images, hashes and byte sizes match [verification.json](../styles/navy-cyan-2026-11-12/evidence/verification.json).
- Both final PNGs independently decoded to `https://q.me-qr.com/k3x1m00q` using OpenCV 4.12.0 on the full files.
- Forty text records per format include the canonical agenda, presenters, projects and subtitles. The nine displayed program intervals are continuous, 08:30–11:00, 150 minutes.
- Five Part 1 titles use equal Bold sizes within each format: 58 px portrait, 67 px landscape. Presenter lines are smaller Italic, non-bold. The native crop shows the correct circumflex and grave in **tầm**.
- Fresh header source: 2172 × 724. Placed at 0.9944751× portrait and 1.0× landscape. The renderer rejects enlargement. Final canvases are 2160 × 3840 and 3840 × 2160.
- Early portrait card collisions and an initial landscape photo enlargement were corrected before final delivery. The portrait QR was subsequently shifted up 15 px to leave an inset below its quiet zone; the final file was rechecked.
- The final PowerShell runner resolves its default output directory after initialization. Native compilation/rendering succeeded. Original logo/QR assets are verified by hash.
- The final reviewer inspected the full posters, the Dashboard text crop and helmet crop; no material blocker remained. Text bounds alone do not prove every optical detail.

All package-local Markdown links resolved. A scoped check of task text files and added skill lines found no credential literals. Original prompts 03/04 remain labeled reconstructed recipes; no unknown historical model, seed or generation prompt is claimed. Schedule consistency is agreement with the selected artwork, not external organizer confirmation.

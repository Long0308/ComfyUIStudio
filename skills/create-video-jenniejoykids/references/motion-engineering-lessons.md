# Motion engineering lessons — applied to the film crew

Source: [beamnxw, Motion Engineering with Opus 5.5](https://x.com/beamnxw/status/2108616740846420354), retrieved through MCP Firecrawl on 2026-10-27 Asia/Bangkok. Full source receipt is episode04/technical/source-research-v001/firecrawl-beamnxw.json. The source describes product motion graphics; it is not evidence of H3 quality, lip synchronization, model capabilities or professional-film acceptance.

Apply its production ideas to JennieJoy:
1. Give each reference one declared purpose: identity, spatial layout, style, lighting or motion. State authority when references disagree.
2. Shot brief includes incoming/outgoing blocking, eye line, camera axis, shot size and planned emotional/visual event. Use wide/medium/close/insert views intentionally; a new angle requires a motivated cut or a plausible continuous move.
3. Store timing in seconds plus explicit native and delivery frame rates, and distinguish scene-local from global frame indices. The current H3 recipe uses native24fps; delivery is30fps. Never reuse a frame number without its rate and time origin.
4. Animate graphics deterministically from the composition frame and fixed seeds. Keep entrances, readable holds and exits separately editable; verify the longest keyword, translation and title.
5. Inspect representative rendered frames first, then normal-speed ranges around neighboring cuts. Stills cannot prove lip timing or motion quality.
6. Give an independent reviewer at most five actionable changes per pass: location, observed defect, specific change, and what must stay fixed. Save actual evidence and verdict scope.
7. Align the perceptual SFX peak to the visible event, not blindly to audio file start. Music, environment, Foley and dialogue stay independently adjustable; review speech intelligibility and the ending.
8. Export and probe the actual Master; inspect/listen to that file, not just the timeline. Save its brief, timing, cue list, hashes and accepted revision.

For episode04 the contract is 84seconds, Master3840x2160 and review2560x1440; source-article square20second examples do not override it. These are process lessons, not a guarantee of Hollywood quality or a replacement for observed AV review.

Use the [engine dispatch contract](engine-dispatch-contract.md) for the responsible owner and downstream consumer. Read [production cases](production-case-studies-20261027.md) before retrying the same failure.

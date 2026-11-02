# Script element -> audio decision (rules used in ep04, reusable for ep05)

## Music

| Script element (where) | Audio decision | ep04 evidence |
|---|---|---|
| Audience 2-4 y, bilingual vocabulary (shot pack `target_keywords`, cards) | Major key, 90-112 BPM, no vocals (vocals fight the dialogue), no hits/drops, steady soft groove | all three candidates |
| Setting: sunny garden + farm fence, cows, picnic table (`visual_description` S01-S06) | Acoustic, small, bright instruments: ukulele, glockenspiel, felt piano, music box/celesta, nylon guitar, marimba, shaker/bongo | NHAC-1/2/3 instrument clauses |
| Dialogue structure: 6 question/answer pairs (`speech_text`) | One continuous bed, even energy; the mix ducks -14 dB under speech; no musical "answers" to lines | style: "steady soft groove, playful but calm" |
| Discovery beats (tokens, cups, wooden arm, recipe book) | Keep in the bed's texture only; the beats get SFX, not musical stingers | no stingers |
| Vocabulary outro: 12 cards x 90 f, word WAV at card start | Bed continues, warm and even, nothing that masks a one-word WAV | length target covers the outro |
| Logo + end plate + 60 f end logo (`motion.ending`) | Bed must still be playing: length >= timeline + 3 s; the mix fades at the end card | bed_min_s = 115 |
| Previous bed (pentatonic pluck, ep03 reuse) rejected by user as not bright/gentle enough | Candidates must differ in instrument set and key from each other and from the old bed | C/100, G/96, F/108 |

### Music style text

Structural clauses (keep verbatim, they encode the safety/mood rules):
`English, long-form extended instrumental, about 2 minutes 30 seconds long, eight sections with intro, repeated themes and outro, instrumental only, no vocals, no singing, gentle cheerful preschool cartoon background music, major key, warm and bright, playful but calm, steady soft groove, no sudden loud hits, no drops, clean mix`

Episode clauses (change per episode, appended after the structural part): `<BPM> BPM, <KEY> major, <instrument list, 4-5 items, the lead melody instrument named>` and optionally one scene word (ep04: "sunny garden morning", "lullaby-like").

Lyrics (instrumental): the empty skeleton, exactly
`[Intro]\n\n[Verse]\n\n[Chorus]\n\n[Verse]\n\n[Chorus]\n\n[Bridge]\n\n[Chorus]\n\n[Outro]` — any word in the lyrics is sung.

Seeds: one integer per candidate, reused across takes (ep04 20261101/02/03) so a take differs only by the text variant.

## SFX

### Cue classes, prompt patterns, durations, starting gains

Negative prompt for every clip: `speech, voice, singing, music, melody, reverb tail, distortion, noise floor, harsh`.
Durations are the requested latent seconds (ComfyUI minimum 1.0 s; measured output ~ requested + 0.1 s); trim at mix time.

| Class | Prompt pattern (fill the bracketed part from the action sentence) | Seconds | Gain start | Pan rule |
|---|---|---|---|---|
| pour / stream (milking into pail) | "Hand milking a cow: rhythmic thin milk streams squirting into an empty metal pail, alternating left-right, soft metallic ring, barn, distant, no music" | 6 (loop) | -22 to -24 dB | toward the station side (+0.35) |
| liquid in container | "Milk sloshing softly inside a sealed glass bottle tilted a few degrees, one small liquid wave settling, close, quiet, no music" | 1.2 | -20 dB | prop side |
| glass/ceramic contact | "A tiny soft ceramic cup clink, single light tap, delicate, quiet, close, no music" | 1.0 | -24 dB (optional) | prop side |
| wood contact / slide | "[N] smooth wooden token(s) placed/sliding on a wooden picnic table, soft light knock(s), quiet, close, no music" | 1.0-1.6 | -18 to -19 dB | +/-0.2 |
| fabric | "A knitted fabric sleeve slid onto a ceramic cup, soft cloth friction, short, quiet, close, no music" | 1.0 | -20 dB | +0.2/+0.3 |
| hinge / mechanism | "A wooden toy arm model with a single hinged elbow bending and straightening, soft wooden hinge creak, two gentle movements, quiet, close, no music" | 1.0 | -20 dB | +0.2 |
| ribbon / tape | "A fabric measuring tape ribbon pulled taut and held, light cloth tension with a faint snap, quiet, close, no music" | 1.0 | -21 dB | 0 |
| page / book | "A small three-panel cardboard picture book unfolding, soft paper and card flaps opening, quiet, close, no music" | 1.0 | -18 dB | +0.1 |
| animal | "A single gentle cow moo, distant, calm dairy cow in a green pasture, soft, no music" | 2.5 | -26 dB | far side (+0.4) |
| whoosh (whip pan only) | "A soft gentle air whoosh for a quick camera pan, short, smooth, airy, no music, no impact" | 1.0 | -16 dB (optional at non-location cuts, -18) | 0 |
| sparkle (icon pop) | "A tiny magical sparkle pop for a cartoon icon appearing, soft glitter shimmer, very short, bright but gentle, no music" | 1.0 | -22 dB | 0 |
| sparkle (card slide) | "A soft gentle sparkle swish for a flashcard sliding in, light glitter, short, warm, no music" | 1.0 | -22 dB | 0 |
| chime (logo) | "A gentle warm two-note chime for a children's channel logo reveal, soft bell, short decay, no music" | 2.0 | -16 dB | 0 |
| leaves | "Gentle leaves rustling in a light breeze, garden trees, soft, natural, no birds, no music" | 1.5 | -24 to -26 dB | 0 |
| ambience (loop) | "Quiet sunny morning garden ambience, soft breeze through leaves, a few distant small birds, calm, no music, no voices" | 12 | -30 dB (optional) | 0 |
| footsteps | "A small child's light footsteps on soft grass, four slow steps, quiet, outdoors, no music" | 2.0 | library only unless walking is on screen | — |

Gains are starting values relative to a dialogue stem at unity (about -16 LUFS integrated); integrated LUFS of 1 s quiet clips is low by construction (ep04 -26 to -55) — judge by peak and by ear in the mix.

### Frame derivation rules (deterministic parts)

1. Action before the line: `frame = dialogue[shot].words[0].startF - lead` with lead 10-25 f, or the v003 cue time if that lane placed the same physical action (prefer measured over guessed).
2. Action during the line: between the two words the sentence names (ep04 heart token between "tastes" and "creamy").
3. Whip pan: `transition.start - 1`. Icon pop: `icon.frame`. Card: `outro_cards[i].start_frame`. Logo chime: first full-logo frame (`logo_disc.in + 5`) and `end_logo.from_frame + 4`.
4. Loops (milking, ambience): start at shot start + 10 f, loop/trim to the shot's end; crossfade 1 s for ambience.
5. **Rejection rule:** if no `visual_description` in any shot shows the action (ep04: pouring, walking) the clip is `placed=false` with the sentence that forbids it quoted in `library_only_reason`.
6. **Direction conflict:** a cue class an earlier editorial manifest excluded (ep04 "no synthetic card stings") stays in the sheet with `optional=true` and the conflict named in the README; the user decides.

### File naming

`SFX-<nn>-<slug>` for clip id, graph folder, ComfyUI output prefix `episodes/<EP>/sfx-v00N/<id>/<id>` and the pick link `SFX-nn-<slug>.wav`; music `NHAC-<n>-<instruments>[-takeK]`, bed `NHAC-n-<instruments>-full-48k.wav`, raw take `*-raw-48k.wav`, preview `NHAC-n-NGHE-THU-30s-co-thoai.wav`, pick links `NHAC-n-nhac-nen-full.wav`.

### Pick sheet

`CHON-AM-THANH.txt` (ASCII Vietnamese ok): header with timeline length and the hard-link note; `=== NHAC NEN ===` one block per
candidate: `<file> | <take> | <length> s | <LUFS>, peak <dBTP>` + loop seam line + "dat o 00:00 ... duck -14 dB" + the preview line
(window, LUFS, music level); `=== SFX ===` one line per clip: `<file> | <action VI> | <s> | <LUFS> | <mm:ss shot[, ...]>` or
`KHONG DAT: <reason>`; footer pointing to the cue sheet JSON and the ComfyUI workflow folders.

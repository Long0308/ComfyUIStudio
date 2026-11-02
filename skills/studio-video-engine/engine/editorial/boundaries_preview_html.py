"""The contact page of ``boundaries preview``: one light-theme HTML file next to the clips (white background).

No script, no external file: ``<video>`` tags point at the gallery's own ``clips/`` and ``posters/``.
"""

from __future__ import annotations

import html

CSS = """
:root{--page:#F7FAFD;--card:#FFFFFF;--ink:#0A2540;--muted:#5C6795;--accent:#0B4FD9;--line:#D5DFEE;--ok:#3E8914;--bad:#D00000;
--okbg:#EAF5E1;--badbg:#FBE8E8;--accbg:#E6EEFC}
*{box-sizing:border-box}
html{background:#FFFFFF}
body{margin:0;background:#FFFFFF;color:var(--ink);font:15px/1.5 "Segoe UI",system-ui,Arial,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:24px 16px 56px}
h1{font-size:26px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 16px}
.banner{background:var(--accbg);border:1px solid var(--accent);border-radius:12px;padding:12px 16px;margin:14px 0}
.banner b{color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;margin-top:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
.media{background:#E9EFF8;aspect-ratio:16/9;position:relative}
.media video{width:100%;height:100%;display:block;object-fit:cover}
.nomedia{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:16px;text-align:center;color:var(--muted)}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:8px}
.name{font:600 17px Consolas,monospace}
.vi{font-weight:600}.en{color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border-radius:999px;padding:2px 10px;font-size:12.5px;border:1px solid var(--line);color:var(--muted);background:#fff}
.chip.ok{background:var(--okbg);border-color:var(--ok);color:var(--ok)}
.chip.bad{background:var(--badbg);border-color:var(--bad);color:var(--bad)}
.chip.acc{background:var(--accbg);border-color:var(--accent);color:var(--accent)}
.meta{font-size:12.5px;color:var(--muted)}
code{background:#F1F5FB;border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:12px;word-break:break-all}
"""


def _chip(text: str, kind: str = "") -> str:
    return f'<span class="chip {kind}">{html.escape(text)}</span>'


def _card(row: dict, boundary: str, swap_hint: str) -> str:
    verdict, tail = row["verdict"], row["tail"]
    if row["status"] == "rendered":
        media = (f'<video controls loop muted playsinline preload="metadata" poster="{html.escape(row["poster"])}" '
                 f'src="{html.escape(row["clip"])}"></video>')
    else:
        media = f'<div class="nomedia">no clip: {html.escape(row["reason"] or "")}</div>'
    if tail["needed"]:
        tails = _chip(f"tail: {tail['native_frames_needed']} native frame(s) beyond the cut"
                      + ("" if tail["available"] else " - NOT available"), "ok" if tail["available"] else "bad")
    else:
        tails = _chip("no tail needed", "ok")
    chips = [_chip(("rule allows: " if verdict["allowed"] else "rule: ") + verdict["text"],
                   "ok" if verdict["allowed"] else "bad"), tails,
             _chip(f"{row['frames']} f" + (f", direction {row['direction']:+d}" if row["direction"] else ""), "acc")]
    seconds = f"render {row['render_seconds']} s" if row["status"] == "rendered" else "not rendered"
    pick = f"{swap_hint} --boundary {boundary} --preset {row['token']}" if swap_hint else ""
    params = ", ".join(f"{k}={v}" for k, v in row["params"].items()) or "no params"
    return (f'<div class="card"><div class="media">{media}</div><div class="body">'
            f'<div class="name">{html.escape(row["preset"])}</div>'
            f'<div><span class="vi">{html.escape(row["label"]["vi"])}</span> '
            f'<span class="en">{html.escape(row["label"]["en"])}</span></div>'
            f'<div class="chips">{"".join(chips)}</div>'
            f'<div class="meta">{html.escape(params)} - {seconds}</div>'
            + (f'<div class="meta">pick it: <code>{html.escape(pick)}</code></div>' if pick else "") + "</div></div>")


def write_index(record: dict) -> str:
    m = record["measured"]
    ncc = "unmeasured" if m.get("ncc") is None else f"{m['ncc']:.3f}"
    cards = "".join(_card(r, record["boundary"], record["swap_hint"]) for r in record["candidates"])
    lo, hi = record["frame_range_from_cut"]
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Transition preview {html.escape(record["boundary"])}</title><style>{CSS}</style></head><body><div class="wrap">'
            f'<h1>Transition preview {html.escape(record["boundary"])} '
            f'({html.escape(record["from"])} to {html.escape(record["to"])})</h1>'
            f'<p class="sub">{record["size"][0]}x{record["size"][1]} at {record["fps"]} fps, frames {lo:+d}..{hi - 1:+d} '
            f'around the cut - whole run {record["render_seconds_total"]} s (source decode {record["decode_seconds"]} s)</p>'
            f'<div class="banner"><b>Measured:</b> framing ncc {ncc} ({html.escape(str(record["framing"]["framing"]))}); '
            f'<b>rule:</b> {html.escape(record["rule"])}; <b>rule picks:</b> {html.escape(record["chosen_by_rule"])}.<br>'
            f'<b>Renderer:</b> {html.escape(record["renderer"])}. {html.escape(record["note"])}.</div>'
            f'<div class="grid">{cards}</div></div></body></html>')

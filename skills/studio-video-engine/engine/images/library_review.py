"""`jjv images library review`: trang HTML duyệt nhân vật (port của script review nhân vật trong docs/review).

Chỉ ĐỌC thư viện; chỉ ghi 1 file HTML (nền trắng, bảng Blue Web, không dark mode, không cam).
Rev theo KHÓA (nhân vật, loại, số prompt): mỗi khóa hiện ảnh của rev mới nhất có khóa đó (kèm nhãn rev);
bản cùng khóa ở rev cũ hơn KHÔNG hiển thị, khóa chỉ có ở rev cũ vẫn hiện.
Cờ khung: ảnh của loại có trong `canvas` (mặc định ACTION=3:4) mà tỉ lệ lệch -> chữ đỏ + liệt kê.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
from typing import Any, NamedTuple, Optional
from urllib.parse import quote

from ..core.errors import Refused
from .library_revs import (BATCH_RE, owns, check_char, classify, KINDS, key_of, matches_canvas, parse_ratio, png_size, rev_of,
                           resolve_revs, split_paths)

CHECKS = ["identity", "wardrobe_r005", "logo N", "real_skin"]
DEFAULT_CANVAS = {"ACTION": "3:4"}
# Bảng màu Blue Web cố định (không dùng màu khác)
PAPER, BG, TEXT, MUTED, ACCENT, BAD, GOOD = (
    "#F7FAFD", "#FFFFFF", "#0A2540", "#5C6795", "#0B4FD9", "#D00000", "#3E8914")
CSS = f"""body{{background:{BG};color:{TEXT};font-family:Segoe UI,Arial,sans-serif;margin:0;padding:24px}}
h1,h2{{color:{TEXT}}}h2{{border-bottom:2px solid {ACCENT};padding-bottom:4px;margin-top:32px}}
h3{{color:{ACCENT};margin:18px 0 6px}}
.muted{{color:{MUTED}}}.row{{display:flex;flex-wrap:wrap;gap:16px}}
.card{{background:{PAPER};border:1px solid {ACCENT};border-radius:6px;padding:10px;width:300px}}
.card img{{width:100%;display:block;border:1px solid {MUTED}}}
a{{color:{ACCENT}}}.meta{{font-size:12px;margin:6px 0;word-break:break-all}}
.bad{{color:{BAD};font-weight:bold}}.good{{color:{GOOD}}}
.chk{{list-style:none;padding:0;margin:6px 0;font-size:13px}}.chk li{{padding:2px 0}}
table{{border-collapse:collapse;margin-top:8px}}
th,td{{border:1px solid {MUTED};padding:6px 12px;text-align:left;font-size:14px}}
th{{background:{PAPER}}}"""


class Take(NamedTuple):
    char: str
    kind: str
    batch: str
    take: str
    img: Path
    prompt: Path
    rec: Optional[dict]
    size: Optional[tuple]
    rev: str = ""


def _load(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def collect(lib: Optional[Path], kind: str, keep: Optional[Any] = None) -> dict[str, list[Take]]:
    """Take của loại `kind` trong `lib`; `keep(rec)` (nếu có) lọc theo receipt."""
    out: dict[str, list[Take]] = {}
    if lib is None or not lib.exists():
        return out
    for bd in sorted(d for d in lib.iterdir() if d.is_dir()):
        m = BATCH_RE.match(bd.name)
        if not m or m.group(3) != kind:
            continue
        for td in sorted(d for d in bd.iterdir() if d.is_dir()):
            for img in sorted(td.glob("*.png")):
                rp = img.with_suffix(".receipt.json")
                rec = _load(rp) if rp.exists() else None
                if keep is not None and not keep(rec, bd.name):
                    continue
                out.setdefault(m.group(2), []).append(Take(
                    m.group(2), kind, bd.name, td.name, img, td / "prompt.txt", rec, png_size(img), rev_of(lib)))
    return out


def collect_current(libs: list[Path], kind: str, cls: dict[str, Any], last: Optional[Path]) -> dict[str, list[Take]]:
    """Take hiện hành theo khóa: rev mới nhất có khóa thắng; take không có khóa chỉ lấy ở rev cuối của loại."""
    out: dict[str, list[Take]] = {}
    for idx, lib in enumerate(libs):
        def keep(rec: Optional[dict], batch: str, idx: int = idx, lib: Path = lib) -> bool:
            k = key_of((rec or {}).get("prompt_id"))
            return owns(cls[kind], k, idx, batch) if k else lib == last
        for c, ts in collect(lib, kind, keep).items():
            out.setdefault(c, []).extend(ts)
    seen: set[tuple[str, str, str]] = set()
    for takes in out.values():
        for take in takes:
            key = key_of((take.rec or {}).get("prompt_id"))
            if key and key in seen:
                raise Refused(f"multiple current images for key {key}; select one take in the source revision")
            if key:
                seen.add(key)
    return out


def take_key(t: Take) -> str:
    pid = (t.rec or {}).get("prompt_id")
    return pid if pid else f"(no receipt) {t.batch}/{t.take}"


def identity_refs(refs_dir: Optional[Path], char: str) -> list[Path]:
    d = refs_dir / char / "references" if refs_dir else None
    return sorted(d.glob("*MASTER_FACE_LOCKED.png")) if d and d.exists() else []


def _rel(p: Path, base: Path) -> str:
    try:
        return quote(os.path.relpath(p, base).replace("\\", "/"), safe="/.-_~")
    except ValueError:  # khác ổ đĩa: dùng file URI tuyệt đối
        return p.resolve().as_uri()


def _bad_canvas(t: Take, canvas: dict[str, tuple[int, int]]) -> bool:
    return t.kind in canvas and not matches_canvas(t.size, canvas[t.kind])


def card(t: Take, base: Path, canvas: dict[str, tuple[int, int]], ratios: dict[str, str]) -> str:
    r, src = t.rec or {}, html.escape(_rel(t.img, base))
    if t.size:
        size_txt = f"{t.size[0]}x{t.size[1]}"
        if t.kind in canvas:
            size_txt = (f"<span class='bad'>{size_txt} (KHÔNG {ratios[t.kind]})</span>" if _bad_canvas(t, canvas)
                        else f"{size_txt} ({ratios[t.kind]})")
    else:
        size_txt = "<span class='bad'>không đọc được PNG</span>"
    prompt_link = (f"<a href='{html.escape(_rel(t.prompt, base))}'>prompt.txt</a>"
                   if t.prompt.exists() else "<span class='bad'>thiếu prompt.txt</span>")
    checks = "".join(f"<li>&#9744; {html.escape(c)}</li>" for c in CHECKS)
    return ("<div class='card'>"
            f"<a href='{src}'><img loading='lazy' src='{src}' alt='{html.escape(t.img.stem)}'></a>"
            "<div class='meta'>"
            f"<b>{html.escape(str(r.get('prompt_id', '(no receipt)')))}</b> · rev {html.escape(t.rev)}<br>"
            f"sha12 {html.escape(t.img.stem)} · acct {html.escape(str(r.get('account_label', '?')))}<br>"
            f"kích thước {size_txt}<br>{prompt_link}</div>"
            f"<ul class='chk'>{checks}</ul></div>")


def ref_card(p: Path, base: Path) -> str:
    if not p.exists():
        return f"<div class='card'><span class='bad'>MISSING {html.escape(p.name)}</span></div>"
    src, sz = html.escape(_rel(p, base)), png_size(p)
    return (f"<div class='card'><a href='{src}'><img loading='lazy' src='{src}'></a>"
            f"<div class='meta'>{html.escape(p.name)}<br><span class='muted'>identity reference</span>"
            f"<br>kích thước {'x'.join(map(str, sz)) if sz else '?'}</div></div>")


def review(libraries: list[Path], out: Path, *, refs_dir: Optional[Path] = None,
           chars: Optional[list[str]] = None, canvas: Optional[dict[str, str]] = None,
           expected: int = 10, title: Optional[str] = None) -> dict[str, Any]:
    """Ghi trang review `out`. libraries: cũ -> mới. Trả thống kê (per_character, canvas_flags, ...)."""
    libs, out = [Path(x) for x in libraries], Path(out)
    ratios = dict(DEFAULT_CANVAS if canvas is None else canvas)
    cv = {k: parse_ratio(v) for k, v in ratios.items()}
    revs = resolve_revs(libs)
    cls = classify(libs)
    data = {k: collect_current(libs, k, cls, revs[k]["current"]) for k in KINDS}
    cl = sorted(check_char(c) for c in chars) if chars else sorted({c for k in KINDS for c in data[k]})
    base = out.parent
    per: dict[str, dict[str, Any]] = {}
    for c in cl:
        f, a = data["FACE"].get(c, []), data["ACTION"].get(c, [])
        per[c] = {"FACE": len({take_key(t) for t in f}), "FACE_takes": len(f),
                  "ACTION": len({take_key(t) for t in a}), "ACTION_takes": len(a),
                  "canvas_flags": [t.img.stem for t in f + a if _bad_canvas(t, cv)],
                  "missing_receipt": [t.img.stem for t in f + a if t.rec is None],
                  "identity_ref": [p.name for p in identity_refs(refs_dir, c)]}
    label = " · ".join(f"{k} {'+'.join(sorted({t.rev for ts in data[k].values() for t in ts}) or ['-'])}"
                       for k in KINDS if revs[k]["current"])
    h = ["<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
         "<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>{html.escape(title or 'review nhân vật FACE/ACTION')}</title><style>{CSS}</style></head><body>",
         f"<h1>{html.escape(title or f'Review {len(cl)} nhân vật')} ({html.escape(label)})</h1>",
         "<p class='muted'>Mỗi khóa (nhân vật, loại, số prompt) lấy từ rev mới nhất có khóa đó (nhãn rev trên thẻ); rev cũ bị thay không hiển thị. "
         "Chạy lại để cập nhật; ảnh còn đang sinh sẽ hiện sau.</p>",
         "<h2>Tổng hợp</h2>",
         "<table><tr><th>Nhân vật</th><th>FACE</th><th>ACTION</th><th>Sai khung</th></tr>"]
    for c in cl:
        n = len(per[c]["canvas_flags"])
        h.append(f"<tr><td>{c}</td><td>{per[c]['FACE']}/{expected}</td><td>{per[c]['ACTION']}/{expected}</td>"
                 f"<td>{f'<span class=bad>{n}</span>' if n else '0'}</td></tr>")
    h.append("</table>")
    for c in cl:
        h.append(f"<h2>{c}</h2>")
        if refs_dir:
            refs = identity_refs(refs_dir, c) or [refs_dir / c / "references" / f"{c}_MASTER_FACE_LOCKED.png"]
            h.append("<h3>Ảnh tham chiếu danh tính</h3><div class='row'>")
            h += [ref_card(p, base) for p in refs] + ["</div>"]
        for k in KINDS:
            rv = "+".join(sorted({t.rev for t in data[k].get(c, [])})) or "-"
            h.append(f"<h3>{k} · {html.escape(rv)} ({len(data[k].get(c, []))} take)</h3>"
                     "<div class='row'>")
            h += [card(t, base, cv, ratios) for t in data[k].get(c, [])] + ["</div>"]
    h.append("</body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(h), encoding="utf-8")
    return {"exit": 0, "output": str(out), "output_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "per_character": {c: {k: per[c][k] for k in ("FACE", "ACTION", "FACE_takes", "ACTION_takes")} for c in cl},
            "canvas_flags": {c: per[c]["canvas_flags"] for c in cl if per[c]["canvas_flags"]},
            "missing_receipts": {c: per[c]["missing_receipt"] for c in cl if per[c]["missing_receipt"]},
            "identity_refs_missing": [c for c in cl if refs_dir and not per[c]["identity_ref"]]}


def register(subparsers: Any) -> None:
    """Gắn `review` vào nhóm `library` (Fable/root nối)."""
    p = subparsers.add_parser("review", help="HTML character review page (red flag for wrong frame ratio)")
    p.add_argument("--library", action="append", required=True, metavar="DIR[,DIR2]")
    p.add_argument("--out", required=True, help="HTML output file")
    p.add_argument("--refs-dir", default=None, help="folder with <CHAR>/references/*MASTER_FACE_LOCKED.png")
    p.add_argument("--canvas", action="append", default=None, metavar="KIND=W:H",
                   help="required frame ratio per kind (default ACTION=3:4)")
    p.add_argument("--title", default=None)
    p.set_defaults(library_func=run_review)


def run_review(args: Any) -> int:
    canvas = dict(x.split("=", 1) for x in args.canvas) if args.canvas else None
    r = review(split_paths(args.library), Path(args.out), refs_dir=Path(args.refs_dir) if args.refs_dir else None,
               canvas=canvas, title=args.title)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return int(r["exit"])

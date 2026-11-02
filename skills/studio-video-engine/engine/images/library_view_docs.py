"""PROMPTS.md / INDEX.json / INDEX.md cho `library view` (deterministic, không timestamp)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from .library_revs import KINDS, posix, rev_of


def fence_for(text: str) -> str:
    """Hàng rào đủ dài để không bị đóng sớm bởi backtick có trong prompt."""
    longest = max((len(mm.group(0)) for mm in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def rev_text(ctx: dict[str, Any]) -> str:
    return " · ".join(f"{k} {'+'.join(ctx['revs'][k].get('used') or [rev_of(ctx['revs'][k]['current'])])}"
                      for k in KINDS if ctx["revs"][k]["current"])


def rejected_dirs(ctx: dict[str, Any]) -> str:
    names = [f"{k}_{rev_of(o)}_rejected" for k in KINDS for o in ctx["revs"][k]["older"]]
    return ", ".join(f"`{n}/`" for n in names) or "(không có)"


def regen_command(q: dict[str, Any], account: str, ctx: dict[str, Any]) -> Optional[str]:
    if not (ctx.get("episode") and ctx.get("machine") and ctx.get("engine_dir")):
        return None
    lib = ctx["libraries"][q["rev"]]
    bdir: Path = q["_batch_dir"]
    return "\n".join([
        f"Set-Location '{ctx['engine_dir']}'",
        "python -I bin/jjv.py images submit"
        f" --episode '{ctx['episode']}' --provider codex-exec"
        f" --prompt-batch '{bdir / (q['batch_id'] + '.json')}' --library-out '{lib}'"
        f" --out '{bdir.parent / ('pool-' + q['rev'])}' --account {account} --machine '{ctx['machine']}'",
    ])


def prompt_section(q: dict[str, Any], res: Optional[dict[str, Any]], ctx: dict[str, Any]) -> list[str]:
    pid, rev = q["prompt_id"], q["rev"]
    out = [f"### {pid}", "", f"- kind: {q['kind']} · rev: `{rev}` · batch file: `{q['batch_id']}.json`"]
    if res:
        rec = res["rec"]
        acc = rec.get("account_label") or "không rõ"
        acc_note = "khớp queue" if acc == q["account"] else f"queue ghi `{q['account']}`, receipt là thực dùng"
        refs, text = rec.get("ref_hashes") or q["ref_images"], res["prompt_text"]
        text_src = f"take `prompt.txt` ({posix(res['prompt_src'])})"
        out += [
            f"- trạng thái: **có ảnh** · take `{res['take']}` · ảnh `{res['entry']['file']}`",
            f"- prompt file: `{res['entry']['prompt_file']}`",
            f"- prompt_sha256 (prompt.txt đã gửi, receipt): `{rec['prompt_sha256']}`",
            f"- brief sha256 (queue prompt_sha256): `{q['prompt_sha256']}`",
            f"- account: `{acc}` ({acc_note})",
        ]
    else:
        refs, text = q["ref_images"], q["brief_text"]
        text_src = "brief `prompt_text` trong batch JSON (chưa có take prompt.txt)"
        out += [
            f"- trạng thái: **chưa có ảnh** (chưa có PNG + receipt trong library-{rev})",
            "- prompt_sha256 (prompt.txt đã gửi): chưa có — chưa render",
            f"- brief sha256 (queue prompt_sha256): `{q['prompt_sha256']}`",
            f"- account: `{q['account']}` (kế hoạch queue, chưa render)",
        ]
    out.append("- ảnh tham chiếu (identity + vai khác, path · sha256):")
    out += [f"  - `{r['role']}` · `{r['path']}` · sha256 `{r['sha256']}`" for r in refs]
    account = res["rec"].get("account_label") if res else q["account"]
    cmd = regen_command(q, account, ctx)
    if cmd:
        out += ["- lệnh regenerate (submit nhận cả batch file):", "```powershell", cmd, "```"]
    fence = fence_for(text)
    out += [f"- prompt text (nguồn: {text_src}):", f"{fence}text", text, fence, ""]
    return out


def build_prompts_md(char: str, qs: list[dict[str, Any]], by_pid: dict[str, dict[str, Any]],
                     ctx: dict[str, Any]) -> str:
    n_img = sum(1 for q in qs if q["prompt_id"] in by_pid)
    pend = [q for q in qs if q["prompt_id"] not in by_pid]
    counts = " · ".join(f"{k} {sum(1 for q in qs if q['kind'] == k)}" for k in KINDS)
    lines = [
        f"# PROMPTS — {char} ({rev_text(ctx)})", "",
        f"> Rev theo khóa (nhân vật, loại, số prompt): rev mới thay rev cũ cùng khóa; ảnh rev cũ đã chuyển sang {rejected_dirs(ctx)} (không xoá).", "",
        "Nguồn chỉ đọc: queue-*.json, `batch-*.json`, take `prompt.txt` + `receipt.json` trong thư viện nguồn.",
        "Prompt có ảnh: byte `prompt.txt` của take đã gửi (sha256 = receipt.prompt_sha256). "
        "Chưa có ảnh: brief trong batch JSON (sha256 = queue.prompt_sha256 = sha256 của prompt_text).",
        "Prompt giữ nguyên byte (có cả CRLF lẫn LF như file gốc). Bản copy cạnh ảnh là `<stem>.prompt.txt`.",
        "Lệnh regenerate nhận theo batch file (10 prompt_id/batch), không theo từng prompt_id.", "",
        f"Tổng {len(qs)} prompt_id ({counts}) · có ảnh {n_img} · chưa có ảnh {len(pend)}", "",
        "## prompt_id chưa có ảnh", "",
    ]
    lines += [f"- `{q['prompt_id']}` — rev `{q['rev']}` · batch `{q['batch_id']}`" for q in pend] or ["- (không có — đủ ảnh)"]
    lines += ["", "## Theo prompt_id", ""]
    for q in qs:
        lines += prompt_section(q, by_pid.get(q["prompt_id"]), ctx)
    return "\n".join(lines) + "\n"


def write_index(out: Path, by_char: dict[tuple[str, str], list[dict[str, Any]]], chars: list[str],
                pending: list[tuple[str, str, str, str, str]], errors: list[str],
                superseded: list[dict[str, Any]], ctx: dict[str, Any]) -> list[str]:
    revs = ctx["revs"]
    characters = {c: {k: sorted(by_char.get((c, k), []), key=lambda e: e["file"]) for k in KINDS} for c in chars}
    sup_by_char: dict[str, int] = {}
    for s in superseded:
        sup_by_char[s["char"]] = sup_by_char.get(s["char"], 0) + 1
    doc = {
        "revs": {k: rev_of(revs[k]["current"]) if revs[k]["current"] else None for k in KINDS},
        "sources": {k: posix(revs[k]["current"]) if revs[k]["current"] else None for k in KINDS},
        "current_revs": {k: revs[k].get("used", []) for k in KINDS},
        "output_root": posix(out),
        "characters": characters,
        "superseded": sorted(superseded, key=lambda e: e["file"]),
        "pending_no_receipt": [f"[{r}] {b}/{t}/{n}: {why}" for r, b, t, n, why in pending],
        "errors": errors,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "INDEX.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    rt = rev_text(ctx)
    npend = lambda c: sum(1 for _, b, _, _, _ in pending if f"-{c}-" in b)  # noqa: E731
    rows = [f"| {c} | {rt} | {len(characters[c]['FACE'])} | {len(characters[c]['ACTION'])} | "
            f"{len(characters[c]['FACE']) + len(characters[c]['ACTION'])} | {npend(c)} | {sup_by_char.get(c, 0)} |"
            for c in chars]
    tf = sum(len(characters[c]["FACE"]) for c in chars)
    ta = sum(len(characters[c]["ACTION"]) for c in chars)
    lines = [f"# by-character — {rt} (bản COPY)", "",
             f"Rev: **{rt}**. Rev cũ bị thay nằm ở `CHAR_XX/<KIND>_<rev>_rejected/` ({rejected_dirs(ctx)}).",
             "Nguồn chỉ đọc. File ở đây là bản copy, không phải hardlink/symlink.", "",
             "| Nhân vật | Rev | FACE | ACTION | Tổng | Chờ receipt | Đã rút (rev cũ) |",
             "|---|---|---:|---:|---:|---:|---:|", *rows,
             f"| **Tổng** | | **{tf}** | **{ta}** | **{tf + ta}** | **{sum(npend(c) for c in chars)}** | "
             f"**{len(superseded)}** |",
             "", "## Chi tiết file", "",
             "| Nhân vật | Loại | rev | Vị trí | prompt_id | sha256 (12) | Trạng thái |",
             "|---|---|---|---|---|---|---|"]
    for c in chars:
        for k in KINDS:
            lines += [f"| {c} | {k} | {e['rev']} | `{e['file']}` | `{e['prompt_id']}` | `{e['sha256'][:12]}` | current |"
                      for e in characters[c][k]]
    lines += [f"| {s['char']} | {s['kind']} | {s['rev']} | `{s['file']}` | `{s['prompt_id']}` | `{s['sha256'][:12]}` | superseded |"
              for s in sorted(superseded, key=lambda e: e["file"])]
    if pending:
        lines += ["", "## Đang chờ (chưa copy)", ""] + [f"- `[{r}] {b}/{t}/{n}` — {why}" for r, b, t, n, why in pending]
    if errors:
        lines += ["", "## Lỗi", ""] + [f"- {e}" for e in errors]
    (out / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows

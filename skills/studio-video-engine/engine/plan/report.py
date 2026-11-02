"""Summary, headline and the human table of a plan document (pure; the JSON document is the product)."""

from __future__ import annotations

from typing import Any

from .planner import GPU_KINDS, UNCERTAIN

UNMEASURED = "?"


def _secs(row: dict) -> str:
    if row["est_seconds"] is None:
        return UNMEASURED
    if row["est_basis"] == "n/a" and row["est_seconds"] == 0:
        return "-"
    return f"{row['est_seconds']:.1f} s [{row['est_basis']}]"


def summarise(rows: list[dict]) -> dict[str, Any]:
    live = [r for r in rows if r["status"] in ("CHANGED", "NEW")]
    priced = [r for r in live if r["est_seconds"] is not None]
    gpu = [r for r in live if r["requires_approval"]]
    kind = "composite.segment" if any(r["kind"] == "composite.segment" for r in rows) else "composite.master"
    segs = [r for r in rows if r["kind"] == kind and r["status"] != "REMOVED"]
    changed_segs = [r for r in segs if r["status"] != "UNCHANGED"]
    frame_s = sum(r["frame_seconds"] or 0 for r in changed_segs)
    call_s = max((r["call_seconds"] for r in segs), default=0.0)
    full_s = sum(r["frame_seconds"] or 0 for r in segs) + call_s
    return {
        "picture_seconds_per_segment_bundle": round(float(frame_s + sum(r["call_seconds"] for r in changed_segs)), 3),
        "picture_seconds_shared_bundle": round(float(frame_s + (call_s if changed_segs else 0.0)), 3),
        "picture_seconds_full_rerender": round(full_s, 3),
        "nodes_total": len([r for r in rows if r["status"] != "REMOVED"]), "nodes_changed": len(live),
        "nodes_reused": len([r for r in rows if r["status"] == "UNCHANGED"]),
        "est_seconds_total": round(float(sum(r["est_seconds"] for r in priced)), 3),
        "est_seconds_cpu": round(float(sum(r["est_seconds"] for r in priced if r["device"] != "gpu")), 3),
        "est_seconds_gpu": round(float(sum(r["est_seconds"] for r in gpu if r["est_seconds"] is not None)), 3),
        "unmeasured_nodes": [r["node"] for r in live if r["est_seconds"] is None],
        "uncertain_nodes": [r["node"] for r in rows if r["status"] == UNCERTAIN],   # an input is named but not on disk
        "gpu_jobs_need_approval": [r["node"] for r in gpu],
        "gpu_unmeasured": [r["node"] for r in gpu if r["est_seconds"] is None],
        "segments_total": len(segs), "segments_recomposite": len(changed_segs),
        "frames_recomposite": sum(r["frames"] for r in changed_segs),
        "frames_total": sum(r["frames"] for r in segs),
        "removed": [r["node"] for r in rows if r["status"] == "REMOVED"],
    }


def headline(rows: list[dict], summary: dict[str, Any]) -> list[str]:
    """Four plain lines: picture, GPU, audio, mux."""
    by = {r["node"]: r for r in rows}
    picture = [r for r in rows if r["kind"] == "composite.segment" and r["status"] in ("CHANGED", "NEW")]
    layers = sorted({layer for r in picture for layer in r.get("layers", [])} - {"cut-points"})
    out = []
    if picture:
        out.append(f"picture: {len(picture)} of {len([r for r in rows if r['kind'] == 'composite.segment'])} segments "
                   f"re-composite ({sum(r['frames'] for r in picture)} f; layers: {', '.join(layers) or 'upstream'}); "
                   f"est {summary['picture_seconds_per_segment_bundle']:.0f} s if every segment bundles, "
                   f"{summary['picture_seconds_shared_bundle']:.0f} s if the bundle is shared, "
                   f"vs {summary['picture_seconds_full_rerender']:.0f} s for one full re-render"
                   + (f"; {len(summary['removed'])} segment(s) removed by the new cut list" if summary["removed"] else ""))
    else:
        out.append("picture: all segments reuse")
    gpu = summary["gpu_jobs_need_approval"]
    out.append(f"GPU: {len(gpu)} job(s) need approval ({', '.join(gpu)}), est {summary['est_seconds_gpu']:.0f} s"
               + (f" + {len(summary['gpu_unmeasured'])} unmeasured" if summary["gpu_unmeasured"] else "")
               if gpu else "GPU: none (no GPU node changed)")
    audio = by.get("audio.mix")
    out.append("audio: unchanged (reuse)" if audio and audio["status"] == "UNCHANGED"
               else f"audio: not comparable ({'; '.join(audio['why'])})" if audio and audio["status"] == UNCERTAIN
               else f"audio: {audio['action']}" if audio else "audio: n/a")
    mux = by.get("mux")
    out.append(f"mux: {mux['action']}" if mux and mux["status"] != "UNCHANGED" else "mux: reuse")
    return out


def _group(rows: list[dict]) -> list[dict]:
    """Changed rows one by one; unchanged rows folded per kind."""
    out, folded = [], {}
    for r in rows:
        if r["status"] == "UNCHANGED":
            folded.setdefault(r["kind"], []).append(r)
        else:
            out.append(r)
    for kind, group in folded.items():
        out.append({"node": f"{kind} x{len(group)}", "status": "UNCHANGED", "why": [], "action": "reuse",
                    "est_seconds": 0.0, "est_basis": "n/a"})
    return out


def table(doc: dict[str, Any], *, verbose: bool = False) -> str:
    rows = doc["rows"] if verbose else _group(doc["rows"])
    cols = [(r["node"], r["status"], "; ".join(r["why"]) or "-", r["action"], _secs(r)) for r in rows]
    head = ("NODE", "STATUS", "WHY (leaf old -> new)", "ACTION", "EST")
    width = [max(len(str(x[i])) for x in [head, *cols]) for i in range(4)]
    width = [min(w, cap) for w, cap in zip(width, (44, 9, 70, 84))]
    fmt = lambda row: "  ".join(str(v)[:w].ljust(w) for v, w in zip(row[:4], width)) + "  " + row[4]  # noqa: E731
    s = doc["summary"]
    unmeasured = f" + {len(s['unmeasured_nodes'])} node(s) unmeasured (?)" if s["unmeasured_nodes"] else ""
    lines = [fmt(head), *[fmt(c) for c in cols], "",
             f"TOTAL  est {s['est_seconds_total']:.1f} s (CPU {s['est_seconds_cpu']:.1f} s, GPU {s['est_seconds_gpu']:.1f} s "
             f"needing approval){unmeasured}  nodes {s['nodes_changed']}/{s['nodes_total']} changed  "
             f"segments {s['segments_recomposite']}/{s['segments_total']}  frames {s['frames_recomposite']}/{s['frames_total']}",
             *doc["headline"]]
    return "\n".join(lines)


def feedback_table(block: dict[str, Any]) -> str:
    """Human view of the additive ``feedback`` block (stderr; advisory: notes never change a row)."""
    if not block["present"]:
        return "\nFEEDBACK  none (no feedback file)"
    live = [n for n in block["notes"] if n["binding"] != "stale"]
    lines = ["", f"FEEDBACK  {block['line_count']} note(s) sha256 {str(block['sha256'])[:12]}  "
                 f"unresolved changes: {len(block['unresolved_changes'])}  (advisory: no row, action or GPU gate is changed)"]
    for n in live:
        where = ", ".join(c["node"] + " " + c["status"] for c in n["related_changed"]) or (
            ", ".join(n["related_nodes"]) + " (unchanged)" if n["related_nodes"] else "unmapped")
        lines.append(f"  [{n['binding']}] L{n['line']} {n['stage']}/{n['shot'] or '-'} {n['verdict']} by {n['author']}: "
                     f"{n['note'][:100]}  -> {where}")
    stale = [n for n in block["notes"] if n["binding"] == "stale"]
    if stale:
        lines.append(f"STALE notes ({len(stale)}; receipt or artifact changed, listed separately):")
        lines += [f"  L{n['line']} {n['stage']}/{n['shot'] or '-'} {n['verdict']} by {n['author']}: {n['note'][:100]}"
                  for n in stale]
    return "\n".join(lines)


__all__ = ["summarise", "headline", "table", "feedback_table", "GPU_KINDS"]

#!/usr/bin/env python3
"""Kiểm độc lập độ bám: so tâm patch (quad đã làm mượt) với tâm vết CHÍNH H3 VẼ trong clip GỐC.

- Vùng chữ: trọng tâm điểm sáng (chữ thêu nhoè) trong cửa sổ quanh quad, ở khung gốc.
- Vùng mũ: trọng tâm vết N đỏ trong cửa sổ quanh quad, ở khung gốc.
Sai số = |tâm quad(t) − tâm vết(t)| − (hiệu cố định đo ở khung 0), tính theo px; báo mean/p95/max.
Không dùng số liệu nội bộ của tracker, chỉ dùng quad đầu ra và khung gốc.
Kèm dải "cửa sổ cố định": crop cùng toạ độ cho các khung liên tiếp để nhìn rung.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tracked_overlay import colour_mask, blob_centroid, quad_bbox, bright_centroid, quad_scale_rot  # noqa: E402

# LƯU Ý TRUNG THỰC: phép đo chữ dùng cùng hàm bright_centroid (lọc thành phần chạm biên) với
# tracker, nên đây là KIỂM NHẤT QUÁN (patch có nằm trên vết H3 không), không phải phép đo độc lập
# hoàn toàn. Kiểm độc lập là dải cửa sổ cố định + bảng đối chiếu nhìn bằng mắt.


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--orig-frames", required=True, type=Path, help="thư mục f_%%04d.png của clip gốc")
    ap.add_argument("--out-frames", required=True, type=Path, help="thư mục f_%%04d.png của clip đã dán")
    ap.add_argument("--track-json", required=True, type=Path)
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--strip", required=True, type=Path)
    ap.add_argument("--strip-frames", default="70,71,72,73,74,75,76,77,78")
    args = ap.parse_args()
    for p in (args.report, args.strip):
        if p.exists():
            raise FileExistsError(f"từ chối ghi đè: {p}")
    track = json.loads(args.track_json.read_text(encoding="utf-8"))
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    kinds = {r["name"]: r["kind"] for r in spec["regions"]}
    quads = {k: np.array(v, dtype=np.float64) for k, v in track["smoothed_quads"].items()}
    files = sorted(args.orig_frames.glob("f_*.png"))
    T = len(files)
    H, W = cv2.imread(str(files[0])).shape[:2]
    result = {}
    series = {k: [] for k in quads}
    for t in range(T):
        img = cv2.imread(str(files[t]))
        for name, q in quads.items():
            qt = q[t]
            pad = 10 if kinds[name] == "text" else 12
            x0, y0, x1, y1 = quad_bbox(qt, pad, pad, W, H)
            vis = ((qt[:, 0] >= 0) & (qt[:, 0] <= W) & (qt[:, 1] >= 0) & (qt[:, 1] <= H)).sum()
            if vis < 4 or x1 - x0 < 6 or y1 - y0 < 6:
                series[name].append(None)
                continue
            roi = img[y0:y1, x0:x1]
            if kinds[name] == "text":
                scale, _ = quad_scale_rot(qt, q[0])
                c, n = bright_centroid(img, qt, (8 * scale, 5 * scale), 15)
            else:
                red = colour_mask(roi, "red")
                c, n = blob_centroid(red, 10)
                if c is not None:
                    ys_, xs_ = np.nonzero(red)
                    # vết N bị cắt ở mép khung → trọng tâm lệch, không đo
                    if (y0 == 0 and ys_.min() <= 1) or (x0 == 0 and xs_.min() <= 1) or \
                       (y1 == H and ys_.max() >= y1 - y0 - 2) or (x1 == W and xs_.max() >= x1 - x0 - 2):
                        c = None
                    else:
                        c = c + np.array([x0, y0])
            if c is None:
                series[name].append(None)
                continue
            series[name].append((qt.mean(axis=0) - c).tolist())
    for name, s in series.items():
        valid = [(i, np.array(v)) for i, v in enumerate(s) if v is not None]
        if not valid or valid[0][0] != 0:
            result[name] = {"error": "không đo được ở khung 0", "frames_measured": len(valid)}
            continue
        base = valid[0][1]
        err = np.array([np.linalg.norm(v - base) for _, v in valid[1:]])
        frames = [i for i, _ in valid[1:]]
        worst = sorted(zip(err.tolist(), frames), reverse=True)[:5]
        result[name] = {
            "kind": kinds[name], "frames_measured": len(valid), "frames_total": T,
            "frames_unmeasurable": [i for i, v in enumerate(s) if v is None],
            "lock_error_px_mean": float(err.mean()) if len(err) else None,
            "lock_error_px_p95": float(np.percentile(err, 95)) if len(err) else None,
            "lock_error_px_max": float(err.max()) if len(err) else None,
            "worst_frames": [{"frame": f, "px": round(e, 2)} for e, f in worst],
            "note": "vết H3 tự nó trôi/đổi hình mỗi khung nên đây là cận trên của sai số bám",
        }
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # dải cửa sổ cố định
    idxs = [int(x) for x in args.strip_frames.split(",")]
    rows = []
    for name in quads:
        if kinds[name] == "text" and name != "LA_text":
            continue
        qs = np.array([quads[name][i] for i in idxs])
        x0, y0, x1, y1 = quad_bbox(qs.reshape(-1, 2), 16, 16, W, H)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        tiles = []
        for i in idxs:
            for src, tag in ((args.orig_frames, "goc"), (args.out_frames, "dan")):
                im = cv2.imread(str(src / f"f_{i + 1:04d}.png"))
                c = cv2.resize(im[y0:y1, x0:x1], (180, int(180 * (y1 - y0) / (x1 - x0))), interpolation=cv2.INTER_CUBIC)
                cv2.putText(c, f"{name} f{i} {tag}", (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 255, 255), 1)
                tiles.append(c)
        pairs = [np.vstack([tiles[k], tiles[k + 1]]) for k in range(0, len(tiles), 2)]
        rows.append(np.hstack(pairs))
    maxw = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, maxw - r.shape[1]), (0, 0))) for r in rows]
    cv2.imwrite(str(args.strip), np.vstack(rows))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("lock_error_px_mean", "lock_error_px_p95", "lock_error_px_max", "frames_measured", "error")} for k, v in result.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

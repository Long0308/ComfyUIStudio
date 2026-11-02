"""Filter graph for the grade: soften -> halation -> grain -> LUT, RGB internally, yuv420p out (tags re-attached).

The LUT is passed by a bare file name (the run copies it next to the render, with cwd set there), so no
Windows drive colon has to be escaped inside the filter graph.
"""
from __future__ import annotations

from dataclasses import dataclass

FLAGS = "accurate_rnd+full_chroma_int"


def matrix_for(color_space: str | None) -> str:
    """YUV<->RGB matrix: the source's own tag (bt709 stays bt709); untagged or SD tags use bt601, which is what
    ffmpeg itself assumes when decoding such a source, so the output decodes exactly like the input did."""
    return "bt709" if color_space == "bt709" else "bt601"


@dataclass(frozen=True)
class GradeParams:
    grain: float = 0.0      # 0..1 -> noise strength 0..20 on its own layer
    halation: float = 0.0   # 0..1 -> red-tinted glow from highlights, screen blend
    soften: float = 0.0     # 0..1 -> gaussian blend (sigma 0.5..2.0 px)

    def __post_init__(self) -> None:
        for name in ("grain", "halation", "soften"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a number in 0..1, got {value!r}")

    def as_dict(self) -> dict:
        return {"grain": float(self.grain), "halation": float(self.halation), "soften": float(self.soften)}


def build_graph(params: GradeParams, lut_file: str, *, matrix: str = "bt601", in_range: str = "tv", tags: str = "") -> str:
    """A -filter_complex string ending in the label [vout]. ``tags`` is an optional ``setparams=...`` segment."""
    if matrix not in ("bt601", "bt709") or in_range not in ("tv", "pc"):
        raise ValueError(f"unsupported matrix {matrix!r} or range {in_range!r}")
    segs = [f"[0:v]scale=in_range={in_range}:in_color_matrix={matrix}:out_range=pc:flags={FLAGS},format=rgb24[v0]"]
    cur = "v0"
    n = 0
    if params.soften > 0:
        nxt = f"v{n + 1}"
        n += 1
        sigma = 0.5 + 1.5 * params.soften
        w = 0.5 * params.soften
        segs.append(f"[{cur}]split=2[s{n}a][s{n}b];[s{n}b]gblur=sigma={sigma:.3f}[s{n}c];"
                    f"[s{n}a][s{n}c]blend=all_expr='A*(1-{w:.3f})+B*{w:.3f}'[{nxt}]")
        cur = nxt
    if params.halation > 0:
        nxt = f"v{n + 1}"
        n += 1
        segs.append(f"[{cur}]split=2[h{n}a][h{n}b];[h{n}b]lutrgb=r='clip((val-190)*2.5\\,0\\,255)'"
                    f":g='clip((val-190)*2.5\\,0\\,255)':b='clip((val-190)*2.5\\,0\\,255)',gblur=sigma=12,"
                    f"colorchannelmixer=rr=1:gg=0.35:bb=0.2[h{n}c];"
                    f"[h{n}a][h{n}c]blend=all_mode=screen:all_opacity={params.halation:.3f}[{nxt}]")
        cur = nxt
    if params.grain > 0:
        nxt = f"v{n + 1}"
        n += 1
        strength = round(20 * params.grain)
        segs.append(f"[{cur}]noise=alls={strength}:allf=t+u[{nxt}]")
        cur = nxt
    tail = f",{tags}" if tags else ""
    segs.append(f"[{cur}]lut3d=file={lut_file}:interp=tetrahedral,"
                f"scale=out_range=tv:out_color_matrix={matrix}:flags={FLAGS},format=yuv420p{tail}[vout]")
    return ";".join(segs)

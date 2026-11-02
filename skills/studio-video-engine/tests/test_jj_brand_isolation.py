from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def test_jenniejoy_config_has_no_newtecons_brand_tokens():
    files = [ROOT / "domains/jenniejoy_cartoon_3d.json", *ROOT.glob("recipes/**/*jenniejoy*.json")]
    assert len(files) > 1
    forbidden = re.compile(r"newtecons|#0b4fd9|#e4302c", re.I)
    hits = [(str(p.relative_to(ROOT)), m.group()) for p in files for m in forbidden.finditer(p.read_text(encoding="utf-8"))]
    assert not hits, hits

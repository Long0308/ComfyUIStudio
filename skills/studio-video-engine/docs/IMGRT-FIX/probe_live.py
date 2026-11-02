"""Read-only r005f provenance probe: no machine/auth loading and no submit."""
import importlib.util
import json
from pathlib import Path
import sys

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL))
from engine.layout.context import Context
from engine.core.io import read_json, sha256_file
from engine.core.errors import Refused

spec = importlib.util.spec_from_file_location("engine.images.codex_queue", Path(__file__).parent / "candidate/codex_queue.py")
queue_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue_module)
repo = queue_module.REPO_ROOT
root = repo / "production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s"
episode = root / "engine/episode.json"
doc = read_json(episode)
ctx = Context(episode, root, doc, doc["domain"], {}, {}, Path("not-loaded"))
folder = repo / "production-local/engine/staging/newtecons-30s/image-batches-r005f"
queue = folder / "queue-r005f.json"
before = sha256_file(queue)
results = []
for batch in sorted(folder.glob("batch-*.json")):
    items = queue_module.load_batch(batch, allowed=[repo.resolve()], forbidden=[], library=True)
    cleared, blocked = 0, 0
    for item in items:
        queue_module._refuse_domain(item, True, ctx)
        if item["dispatch_allowed"] is True:
            queue_module._refuse_blocked(item, True, ctx=ctx)
            cleared += 1
        else:
            try:
                queue_module._refuse_blocked(item, True, ctx=ctx)
            except Refused:
                blocked += 1
            else:
                raise AssertionError("blocked row passed")
    results.append({"batch": batch.name, "items": len(items), "cleared": cleared, "blocked": blocked})
assert before == sha256_file(queue), "live queue changed during read-only probe"
report = {"episode": str(episode), "queue": str(queue), "queue_sha256": before,
          "submitted": False, "results": results, "total": sum(r["items"] for r in results)}
print(json.dumps(report, indent=2))
Path(__file__).with_name("live-probe.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")

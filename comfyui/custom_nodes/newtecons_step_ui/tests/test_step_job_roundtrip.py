"""Round trip: step_routes record -> host runner validation (bug: runner rejected every video job)."""
import asyncio, importlib.util, json, sys, tempfile, types, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG / "tools"))
import host_step_runner as runner  # noqa: E402
import step_job_contract as contract  # noqa: E402


def load_routes():
    pkg = types.ModuleType("nt_step_pkg"); pkg.__path__ = [str(PKG)]
    sys.modules["nt_step_pkg"] = pkg
    for name in ("step_job_contract", "step_routes"):
        spec = importlib.util.spec_from_file_location(f"nt_step_pkg.{name}", PKG / f"{name}.py")
        mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
    return sys.modules["nt_step_pkg.step_routes"]


class FakeRoutes:
    def __init__(self): self.handlers = {}
    def post(self, path): return lambda fn: self.handlers.setdefault(("POST", path), fn) and fn
    def get(self, path): return lambda fn: self.handlers.setdefault(("GET", path), fn) and fn


class FakeRequest:
    def __init__(self, body): self._body = body
    async def json(self): return self._body


BODY = {"verb": "post.logo", "shot": "S02_A", "episode": "Newtecons-TienDo-KichTinh-30s",
        "args": {"video": "a/b.mp4", "out": "production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/o.mp4",
                 "enabled": True}}


class RoundTrip(unittest.TestCase):
    def post(self, body):
        routes_mod = load_routes()
        with tempfile.TemporaryDirectory() as tmp:
            routes_mod.JOB_ROOT = Path(tmp)
            table = FakeRoutes(); routes_mod.register_routes(table)
            resp = asyncio.run(table.handlers[("POST", "/newtecons/step/run")](FakeRequest(body)))
            files = list(Path(tmp).glob("*.request.json"))
            return resp, [json.loads(f.read_text(encoding="utf-8")) for f in files]

    def test_route_record_is_accepted_by_runner(self):
        resp, records = self.post(BODY)
        self.assertEqual(resp.status, 202)
        rec = records[0]
        self.assertEqual(set(rec["request"]), {"verb", "shot", "episode", "args", "domain", "preview"})
        out = runner.load_request(rec, rec["job_id"])
        self.assertEqual(out["verb"], "post.logo")
        argv = contract.build_argv(out, jjv=Path("jjv.py"), repo_root=Path("."))
        self.assertIn("logo", argv)

    def test_runner_still_enforces_domain_and_preview(self):
        _, records = self.post(BODY)
        rec = records[0]
        for key, val in (("domain", "jenniejoy_cartoon_3d"), ("preview", False)):
            bad = json.loads(json.dumps(rec)); bad["request"][key] = val
            with self.assertRaises(contract.RequestError):
                runner.load_request(bad, bad["job_id"])
        bad = json.loads(json.dumps(rec)); bad["request"]["extra"] = 1
        with self.assertRaises(contract.RequestError):
            runner.load_request(bad, bad["job_id"])
        bad = json.loads(json.dumps(rec)); del bad["request"]["domain"]
        with self.assertRaises(contract.RequestError):
            runner.load_request(bad, bad["job_id"])
        with self.assertRaises(contract.RequestError):
            runner.load_request(rec, "0" * 32)

    def test_every_verb_round_trips(self):
        for verb, keys in contract.SCHEMAS.items():
            req = {"verb": verb, "shot": "S02_A", "episode": "ep", "args": {}}
            need = {"seedvr2.plan": {"out"}, "seedvr2.execute": {"plan"}, "post.logo": {"video", "out"},
                    "timing.words": {"dialogue", "out"},
                    "captions.burn": {"video", "timing", "timing_receipt", "subtitles", "font", "wav", "out"},
                    "edit.assemble": {"edl", "out_dir", "tag"}}[verb]
            req["args"] = {k: "x/y" for k in need}
            if verb == "edit.assemble": req["args"]["tag"] = "t"
            _, records = self.post(req)
            runner.load_request(records[0], records[0]["job_id"])


if __name__ == "__main__":
    unittest.main()

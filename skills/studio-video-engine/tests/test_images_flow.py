"""images plan -> adopt -> compare -> approve -> native: receipts bind every step to a sha256 (CLI wiring, in process)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from engine.core.errors import Refused
from engine.images import approve as approve_mod
from engine.images import receipts
from images_fixtures import LIVE, World, make_png, run_images, sha

ITEMS = ["identity", "headcount", "enclosure", "listener_mouth_closed", "no_text", "costume_print_side"]


class Flow:
    def __init__(self, tmp: Path, domain: str = "jenniejoy_cartoon_3d") -> None:
        self.tmp = tmp
        self.world = World(tmp, domain=domain)
        self.layout, self.out = tmp / "layout", tmp / "images"
        self.world.plan_layout(self.layout)
        self.world.images_plan(self.out, self.layout, shots=("S01_A", "S02_A"))
        self.prompt = tmp / "p.txt"
        self.prompt.write_text("make the frame", encoding="utf-8")
        self.base = ["--episode", str(self.world.root), "--out", str(self.out), "--machine", str(self.world.machine_path)]

    def run(self, verb: str, *argv: str):
        return run_images([verb, *self.base, *argv])

    def adopt(self, name: str = "gpt1.png", color=(10, 90, 40), size=(1672, 941), shot: str = "S01_A", **extra):
        png = make_png(self.tmp / name, color, size)
        argv = ["--shot", shot, "--file", str(png), "--route", "codex-builtin", "--prompt-file", str(self.prompt),
                "--refs-from-plan", "--source-path", "C:/x/generated_images/abc/exec-1.png"]
        return self.run("adopt", *argv, *extra.get("more", [])), png

    def fill_checklist(self, shot: str, sha_full: str, status: str = "pass") -> Path:
        path = self.out / shot / "compare" / "checklist.json"
        sheet = json.loads(path.read_text("utf-8"))
        for item in ITEMS:
            sheet["candidates"][sha_full][item] = {"status": status, "note": "looked at the pixels"}
        path.write_text(json.dumps(sheet), encoding="utf-8")
        return path


def test_plan_binds_guide_placement_cast_refs_and_lists_the_providers_by_domain(tmp_path):
    flow = Flow(tmp_path)
    plan = receipts.load_plan(flow.out)
    row = receipts.plan_shot(plan, "S01_A")
    assert len(row["guide"]["sha256"]) == 64 and len(row["placement"]["sha256"]) == 64
    assert [r["role"] for r in row["refs"]] == ["mother", "alice"]
    providers = {p["provider"]: p for p in row["providers"]}
    assert all(providers[p]["allowed"] for p in ("comfyui-local", "openrouter", "codex-adopt", "codex-exec"))
    assert providers["comfyui-local"]["qualification"] == "unqualified" and "key_present" in providers["openrouter"]
    live = Flow(tmp_path / "live", domain=LIVE)
    live_providers = {p["provider"]: p["allowed"] for p in receipts.plan_shot(receipts.load_plan(live.out), "S01_A")["providers"]}
    assert live_providers == {"comfyui-local": True, "openrouter": False, "codex-adopt": True, "codex-exec": True}  # routes-v002, user 2026-10-30


def test_plan_is_refused_without_a_guide_or_placement_text_and_a_changed_file_is_caught(tmp_path):
    flow = Flow(tmp_path)
    code, out = run_images(["plan", *flow.base, "--layout", str(flow.layout), "--shot", "S03_A"])
    assert code == 1 and "no guide PNG" in out["error"]
    plan = receipts.load_plan(flow.out)
    Path(receipts.plan_shot(plan, "S01_A")["guide"]["path"]).write_bytes(b"\x89PNG\r\n\x1a\nchanged")
    code, out = flow.adopt()[0]
    assert code == 1 and "changed since the plan" in out["error"]


def test_adopt_records_route_models_prompt_refs_and_sha_with_unexposed_ids_as_null(tmp_path):
    flow = Flow(tmp_path)
    (code, summary), png = flow.adopt()
    assert code == 0 and summary["route"] == "codex-builtin"
    assert summary["requested_model"] == "GPT Image Gen 2" and summary["resolved_model"] is None and summary["runtime_id"] is None
    assert summary["sha256"] == sha(png) and summary["prompt_sha256"] == sha(flow.prompt) and len(summary["ref_hashes"]) == 3
    receipt = receipts.find_receipt(flow.out, "S01_A", summary["sha256"][:10])
    assert receipt["output"]["width"] == 1672 and receipt["source_path"].endswith("exec-1.png") and receipt["guide"]["sha256"]
    assert Path(receipt["output"]["path"]).read_bytes() == png.read_bytes()


def test_adopt_refuses_unknown_routes_missing_refs_and_the_same_bytes_twice(tmp_path):
    flow = Flow(tmp_path)
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    common = ["--shot", "S01_A", "--file", str(png), "--prompt-file", str(flow.prompt)]
    assert flow.run("adopt", *common, "--route", "manual", "--refs-from-plan")[0] == 1
    code, out = flow.run("adopt", *common, "--route", "codex-builtin")
    assert code == 1 and "name the reference images" in out["error"]
    assert flow.run("adopt", *common, "--route", "codex-builtin", "--refs-from-plan")[0] == 0
    code, out = flow.run("adopt", *common, "--route", "codex-builtin", "--refs-from-plan")
    assert code == 1 and "already has a receipt" in out["error"]
    assert flow.run("adopt", "--shot", "S01_A", "--file", str(tmp_path / "x.txt"), "--route", "codex-builtin",
                    "--prompt-file", str(flow.prompt), "--refs-from-plan")[0] == 1


def test_live_action_accepts_adopt_since_routes_v002_hybrid(tmp_path):
    flow = Flow(tmp_path, domain=LIVE)
    home = tmp_path / "home"
    flow.world.machine["images"] = {"codex_accounts": [{"label": "acct1", "codex_home": str(home)}]}  # N25: source must be proven
    flow.world.write_machine()
    png = make_png(tmp_path / "live.png", (10, 90, 40), (1672, 941))
    (home / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a").mkdir(parents=True)
    (home / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "exec-1.png").write_bytes(png.read_bytes())  # N25b: the source must exist, same bytes
    from images_fixtures import write_rollout
    write_rollout(home, "019a3c1e-0000-7000-8000-00000000000a", "exec-1.png")
    code, out = flow.run("adopt", "--shot", "S01_A", "--file", str(png), "--route", "codex-builtin", "--prompt-file", str(flow.prompt),
                         "--refs-from-plan", "--requested-model", "gpt-image-2",
                         "--source-path", str(home / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "exec-1.png"))
    assert code == 0 and out["route"] == "codex-builtin"


def test_compare_makes_one_sheet_and_a_checklist_that_re_runs_do_not_clobber(tmp_path):
    flow = Flow(tmp_path)
    (_, first), _ = flow.adopt("g1.png", (10, 90, 40))
    code, cmp1 = flow.run("compare", "--shot", "S01_A")
    assert code == 0 and cmp1["checklist_items"] == ITEMS
    sheet = Image.open(cmp1["sheet"])
    assert sheet.width > 1000 and sheet.height > 300
    path = flow.fill_checklist("S01_A", first["sha256"])
    (_, second), _ = flow.adopt("g2.png", (90, 10, 40))
    code, cmp2 = flow.run("compare", "--shot", "S01_A")
    assert code == 0 and cmp2["sheet"] != cmp1["sheet"] and len(cmp2["candidates"]) == 2
    document = json.loads(path.read_text("utf-8"))
    assert document["candidates"][first["sha256"]]["identity"]["status"] == "pass"            # reviewed entry kept
    assert document["candidates"][second["sha256"]]["identity"]["status"] == "unreviewed"
    assert flow.run("compare", "--shot", "S01_A")[1]["sheet"] == cmp2["sheet"]               # idempotent


def test_approve_needs_every_item_pass_a_reviewer_a_scope_and_a_known_sha(tmp_path):
    flow = Flow(tmp_path)
    (_, adopted), _ = flow.adopt()
    full = adopted["sha256"]
    flow.run("compare", "--shot", "S01_A")
    args = ["--shot", "S01_A", "--sha", full[:12], "--reviewer", "root", "--scope", "opening still"]
    code, out = flow.run("approve", *args)
    assert code == 1 and "not 'pass'" in out["error"]
    path = flow.fill_checklist("S01_A", full, "pass")
    sheet = json.loads(path.read_text("utf-8"))
    sheet["candidates"][full]["no_text"]["status"] = "fail"
    path.write_text(json.dumps(sheet), encoding="utf-8")
    code, out = flow.run("approve", *args)
    assert code == 1 and "no_text" in out["error"]
    flow.fill_checklist("S01_A", full, "pass")
    assert flow.run("approve", "--shot", "S01_A", "--sha", full[:12], "--reviewer", " ", "--scope", "x")[0] == 1
    code, ok = flow.run("approve", *args)
    assert code == 0 and ok["candidate_sha256"] == full and Path(ok["approval"]).name == "approval-v001.json"
    assert flow.run("approve", "--shot", "S01_A", "--sha", "deadbeef00", "--reviewer", "r", "--scope", "s")[0] == 1
    assert flow.run("approve", "--shot", "S02_A", "--sha", full[:12], "--reviewer", "r", "--scope", "s")[0] == 1   # other shot
    row = json.loads(Path(ok["approval"]).read_text("utf-8"))
    assert row["receipt_sha256"] and row["plan_sha256"] and row["guide_sha256"] and row["status"] == "accepted_image"


def test_native_makes_864x480_for_an_approved_sha_only_and_records_the_source(tmp_path):
    flow = Flow(tmp_path)
    (_, adopted), _ = flow.adopt()
    full = adopted["sha256"]
    code, out = flow.run("native", "--shot", "S01_A", "--sha", full[:12])
    assert code == 1 and "no current approval" in out["error"]
    flow.run("compare", "--shot", "S01_A")
    flow.fill_checklist("S01_A", full)
    assert flow.run("approve", "--shot", "S01_A", "--sha", full[:12], "--reviewer", "root", "--scope", "still")[0] == 0
    code, native = flow.run("native", "--shot", "S01_A", "--sha", full[:12])
    assert code == 0 and native["anchor_approved"] is True and not native["reused"]
    image = Image.open(native["native"]["path"])
    assert image.size == (864, 480) and native["native"]["sha256"] == sha(Path(native["native"]["path"]))
    row = json.loads(Path(native["receipt"]).read_text("utf-8"))
    assert row["source"]["sha256"] == full and row["source"]["width"] == 1672
    assert 1.0 < row["native"]["aspect_stretch_pct"] < 1.5                                   # 16:9 -> 1.8:1 plain resize
    assert flow.run("native", "--shot", "S01_A", "--sha", full[:12])[1]["reused"] is True


def test_native_allows_an_unapproved_diagnostic_copy_and_refuses_a_wrong_aspect_unless_cropped(tmp_path):
    flow = Flow(tmp_path)
    (_, adopted), _ = flow.adopt("square.png", (5, 5, 5), (900, 900))
    full = adopted["sha256"]
    code, out = flow.run("native", "--shot", "S01_A", "--sha", full[:12], "--allow-unapproved")
    assert code == 1 and "aspect" in out["error"]
    code, native = flow.run("native", "--shot", "S01_A", "--sha", full[:12], "--allow-unapproved", "--center-crop")
    assert code == 0 and native["anchor_approved"] is False
    assert json.loads(Path(native["receipt"]).read_text("utf-8"))["native"]["crop"]["box"] == [0, 200, 900, 700]


def test_a_tampered_candidate_or_a_stale_approval_is_never_used(tmp_path):
    flow = Flow(tmp_path)
    (_, adopted), _ = flow.adopt()
    full = adopted["sha256"]
    flow.run("compare", "--shot", "S01_A")
    flow.fill_checklist("S01_A", full)
    flow.run("approve", "--shot", "S01_A", "--sha", full[:12], "--reviewer", "root", "--scope", "still")
    assert approve_mod.current_approval(flow.out, "S01_A")["candidate_sha256"] == full
    receipt = receipts.find_receipt(flow.out, "S01_A", full[:12])
    Path(receipt["output"]["path"]).write_bytes(b"\x89PNG\r\n\x1a\ntampered")
    assert approve_mod.current_approval(flow.out, "S01_A") is None
    with pytest.raises(Refused, match="no longer matches its receipt"):
        approve_mod.verified_candidate(flow.out, "S01_A", full[:12])
    assert flow.run("native", "--shot", "S01_A", "--sha", full[:12])[0] == 1


def test_no_anchor_without_a_receipt_a_loose_png_in_the_folder_is_not_a_candidate(tmp_path):
    flow = Flow(tmp_path)
    loose = make_png(flow.out / "S01_A" / "candidates" / "abcdef012345.png")
    assert flow.run("native", "--shot", "S01_A", "--sha", sha(loose)[:12])[0] == 1
    assert flow.run("approve", "--shot", "S01_A", "--sha", sha(loose)[:12], "--reviewer", "r", "--scope", "s")[0] == 1
    assert flow.run("compare", "--shot", "S01_A")[0] == 1                                   # nothing registered to compare


def test_layout_and_images_register_next_to_every_existing_jjv_stage_without_a_name_clash():
    """The CLI-PATCH wires these two registrations into bin/jjv.py: prove they coexist with the real parser."""
    import importlib.util

    from engine.images import cli as images_cli
    from engine.layout import cli as layout_cli

    spec = importlib.util.spec_from_file_location("jjv_bin", Path(__file__).resolve().parents[1] / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.build_parser()
    stages = next(a for a in parser._actions if a.dest == "stage")
    if "layout" not in stages.choices:                       # not wired yet: add them the way the patch does
        layout_cli.register_cli(stages)
        images_cli.register_cli(stages)
    args = parser.parse_args(["images", "submit", "--episode", "e", "--out", "o", "--shot", "S", "--provider", "codex-exec",
                              "--prompt-file", "p.txt", "--dry-run"])
    assert (args.stage, args.verb, args.provider, args.dry_run) == ("images", "submit", "codex-exec", True)
    assert parser.parse_args(["layout", "render", "--brief", "b.json", "--out", "o", "--shot", "S"]).passes == "beauty,depth,mask"
    assert {"plan", "check", "render"} <= set(next(a for a in stages.choices["layout"]._actions if a.dest == "verb").choices)

"""N89-P0: `jjv images library plan|run|status`. Plan: round-robin + lane phụ cùng codex_home, từ chối tài khoản cooling,
machine.json không bị ghi. Run: một tiến trình con mỗi lane (python -I bin/jjv.py ... library lane), resume bỏ take đã có,
lane dừng vì quota trong khi lane khác chạy tiếp. Status: đếm đúng theo nhân vật/kind. FAKE codex only (tests/fake_codex.py)."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from engine.core.errors import Refused, Uncertain
from engine.images import library_run, library_status, pool
from images_fixtures import run_images, sha
from test_images_n23fix import Lib

B1, B2, B3, B4, B5 = ("batch-01-CHAR_01-FACE", "batch-02-CHAR_01-ACTION", "batch-03-CHAR_02-FACE", "batch-04-CHAR_02-ACTION",
                      "batch-05-CHAR_03-FACE")
FOUR = [(B1, "CHAR_01", "FACE", 1), (B2, "CHAR_01", "ACTION", 1), (B3, "CHAR_02", "FACE", 1), (B4, "CHAR_02", "ACTION", 1)]


class Farm:
    """Lib (NEWTECONS-domain world, 2 fake accounts) + a queue in the real shape + one batch file per queue batch_id."""

    def __init__(self, tmp: Path, batches: list[tuple[str, str, str, int]], monkeypatch=None) -> None:
        self.lib, self.tmp = Lib(tmp), tmp
        if monkeypatch is not None:
            monkeypatch.setenv("FAKE_CODEX_PNG", str(self.lib.png))  # the lane processes inherit it
        self.rows = []
        for bid, char, kind, count in batches:
            path = self.lib.batch_file(bid, count, id_prefix=f"{char}_{kind}", auto_queue=False)
            for item in json.loads(path.read_text("utf-8")):
                self.rows.append({"prompt_id": item["prompt_id"], "batch_id": bid, "char": char, "kind": kind, "dispatch_allowed": True,
                                  "prompt_sha256": hashlib.sha256(item["prompt_text"].encode("utf-8")).hexdigest()})
        self.queue = self.lib.world.root / "staging" / "queue-r005.json"  # legacy domain-less queue lives under the episode staging (IMGRT gap 1)
        self.queue.parent.mkdir(parents=True, exist_ok=True)
        for bid, *_ in batches:
            shutil.copy(tmp / f"{bid}.json", self.queue.parent / f"{bid}.json")
        self.write_queue()
        self.plan, self.pool_out = tmp / "plans" / "plan.json", tmp / "pool"

    def write_queue(self) -> None:
        self.queue.write_text(json.dumps(self.rows), encoding="utf-8")

    def block(self, prompt_id: str) -> None:
        next(r for r in self.rows if r["prompt_id"] == prompt_id)["dispatch_allowed"] = False
        self.write_queue()

    def plan_args(self, accounts: str = "acct1,acct2", procs: int = 2, **extra: str) -> list[str]:
        argv = ["library", "plan", "--queue", str(self.queue), "--accounts", accounts, "--procs-per-account", str(procs),
                "--out", str(self.plan), "--machine", str(self.lib.world.machine_path), "--episode", str(self.lib.world.root),
                "--library-out", str(self.lib.lib_out), "--pool-out", str(self.pool_out)]
        for key, value in extra.items():
            argv += [f"--{key.replace('_', '-')}", str(value)]
        return argv

    def run(self, *extra: str) -> tuple[int, dict]:
        return run_images(["library", "run", "--plan", str(self.plan), *extra])

    def status(self) -> dict:
        code, out = run_images(["library", "status", "--plan", str(self.plan), "--json"])
        assert code == 0, out
        return out

    def home(self, label: str) -> Path:
        return next(a for a in self.lib.accounts if a.label == label).codex_home

    def state_path(self) -> Path:
        return self.pool_out / "codex-pool-state.json"


def status_file(farm: Farm) -> dict:
    return json.loads(library_status.status_path(farm.plan).read_text("utf-8"))


# --- plan -----------------------------------------------------------------------------------------------------

def test_plan_round_robin_lane_variants_and_machine_untouched(tmp_path):
    farm = Farm(tmp_path, [*FOUR, (B5, "CHAR_03", "FACE", 1)])
    before = sha(farm.lib.world.machine_path)
    code, out = run_images(farm.plan_args())
    assert code == 0, out
    assert [(l["label"], l["batches"]) for l in out["lanes"]] == [("acct1", [B1, B5]), ("acct1b", [B2]), ("acct2", [B3]), ("acct2b", [B4])]
    plan = json.loads(farm.plan.read_text("utf-8"))
    assert plan["schema"] == "jjv/images-library-plan/v1" and plan["rev"] == "r005" and out["prompt_ids"] == 5
    for lane in plan["lanes"]:
        assert lane["codex_home"] == farm.home(lane["account"]).as_posix()  # a variant is the SAME account
        assert lane["variant"] == (lane["label"] != lane["account"])
    assert plan["batches"][B1]["lane"] == "acct1" and plan["batches"][B1]["prompt_ids"] == ["CHAR_01_FACE_1_r005"]
    assert plan["batches"][B1]["items"][0] == {"prompt_id": "CHAR_01_FACE_1_r005", "char": "CHAR_01", "kind": "FACE",
                                               "prompt_sha256": farm.rows[0]["prompt_sha256"]}
    assert sha(farm.lib.world.machine_path) == before  # never written


def test_plan_skips_blocked_rows_filters_kinds_and_is_write_once(tmp_path):
    farm = Farm(tmp_path, [(B1, "CHAR_01", "FACE", 2), (B2, "CHAR_01", "ACTION", 1), (B3, "CHAR_02", "FACE", 1)])
    farm.block("CHAR_01_FACE_1_r005")
    code, out = run_images(farm.plan_args(kinds="FACE"))
    assert code == 0, out
    plan = json.loads(farm.plan.read_text("utf-8"))
    assert set(plan["batches"]) == {B1, B3} and plan["batches"][B1]["prompt_ids"] == ["CHAR_01_FACE_2_r005"]
    assert plan["batches"][B1]["skipped_in_file"] == 1 and plan["kinds"] == ["FACE"]
    code, out = run_images(farm.plan_args(kinds="FACE"))
    assert code == 1 and "exists" in out["error"]


def test_plan_refuses_a_cooling_account_or_a_cooling_variant_label(tmp_path):
    farm = Farm(tmp_path, FOUR)
    pool.update_state(farm.state_path(), lambda s: pool.mark_cooling(s, "acct2", time.time() + 3600, "quota"))
    code, out = run_images(farm.plan_args())
    assert code == 1 and "cooling" in out["error"] and "acct2" in out["error"] and not farm.plan.exists()

    def swap(state: dict) -> None:
        pool.mark_good(state, "acct2")
        pool.mark_cooling(state, "acct1b", time.time() + 3600, "quota")

    pool.update_state(farm.state_path(), swap)
    code, out = run_images(farm.plan_args())
    assert code == 1 and "acct1b" in out["error"]  # a variant label is the same ChatGPT account
    pool.update_state(farm.state_path(), lambda s: s["cooling"].update({"acct1b": time.time() - 1}))
    code, out = run_images(farm.plan_args())
    assert code == 0 and out["cooling_checked"] is True, out


def test_plan_refuses_unknown_account_missing_auth_and_bad_procs(tmp_path):
    farm = Farm(tmp_path, FOUR)
    code, out = run_images(farm.plan_args(accounts="acct1,acct9"))
    assert code == 1 and "acct9" in out["error"]
    code, out = run_images(farm.plan_args(procs=0))
    assert code == 1 and "procs-per-account" in out["error"]
    (farm.home("acct2") / "auth.json").unlink()
    code, out = run_images(farm.plan_args())
    assert code == 1 and "auth.json" in out["error"] and not farm.plan.exists()


# --- run ------------------------------------------------------------------------------------------------------

def test_run_dry_run_lists_lanes_with_the_submit_argv_and_writes_nothing(tmp_path, monkeypatch):
    farm = Farm(tmp_path, FOUR, monkeypatch)
    assert run_images(farm.plan_args())[0] == 0
    code, out = farm.run("--dry-run")
    assert code == 0 and out["dry_run"] and out["ready"], out
    lanes = {l["label"]: l for l in out["lanes"]}
    variant = lanes["acct1b"]["batches"][0]["argv"]
    assert variant[:2] == ["submit", "--episode"] and "--provider" in variant and variant[variant.index("--provider") + 1] == "codex-exec"
    assert variant[variant.index("--account") + 1] == "acct1b"
    assert variant[variant.index("--codex-account") + 1] == f"acct1b={farm.home('acct1').as_posix()}"
    assert "--codex-account" not in lanes["acct1"]["batches"][0]["argv"]
    base = lanes["acct1"]["batches"][0]["argv"]
    assert base[base.index("--library-out") + 1] == farm.lib.lib_out.resolve().as_posix()
    assert out["totals"] == {"wanted": 4, "done": 0, "remaining": 4}
    assert not library_status.runs_dir(farm.plan).exists() and not library_status.status_path(farm.plan).exists()
    assert not farm.lib.lib_out.exists() and not farm.lib.calls("acct1") and not farm.lib.calls("acct2")


def test_run_resumes_skipping_a_valid_take_and_remaking_a_damaged_one(tmp_path, monkeypatch):
    farm = Farm(tmp_path, [(B1, "CHAR_01", "FACE", 2), (B2, "CHAR_01", "ACTION", 2)], monkeypatch)
    assert run_images(farm.plan_args(accounts="acct1", procs=1))[0] == 0
    first = farm.lib.run(farm.queue.parent / f"{B1}.json", account="acct1")  # batch-01 made earlier through the existing submit path
    assert len(first["takes"]) == 2
    damaged = Path(json.loads(Path(first["takes"][1]["receipt"]).read_text("utf-8"))["output"]["path"])
    damaged.write_bytes(damaged.read_bytes() + b"x")
    before = len(farm.lib.calls("acct1"))
    code, out = farm.run()
    assert code == 0, out
    assert len(farm.lib.calls("acct1")) - before == 3  # the damaged take + the two of batch-02; the valid take is skipped
    run_doc = json.loads((Path(out["run_dir"]) / "run.json").read_text("utf-8"))
    assert run_doc["lanes"]["acct1"]["batches"][0]["remaining"] == ["CHAR_01_FACE_2_r005"]
    filtered = json.loads(Path(run_doc["lanes"]["acct1"]["batches"][0]["file"]).read_text("utf-8"))
    assert [i["prompt_id"] for i in filtered] == ["CHAR_01_FACE_2_r005"]
    assert (Path(out["run_dir"]) / "batches" / "queue-r005.json").read_bytes() == farm.queue.read_bytes()  # the N52 gate travels
    status = status_file(farm)
    assert status["totals"] == {"wanted": 4, "done": 4, "remaining": 0}
    lane = status["lanes"][0]
    assert lane["state"] == "done" and [b["images"] for b in lane["batches"]] == [1, 2]
    receipts = sorted((farm.lib.lib_out / B1).glob("t*/*.receipt.json"))
    assert [p.parent.name for p in receipts] == ["t001", "t002", "t003"]
    code, out = farm.run()  # nothing left: no lane process, no codex call
    assert code == 0 and out["pids"] == {} and len(farm.lib.calls("acct1")) - before == 3
    assert status_file(farm)["lanes"][0]["state"] == "done"


def test_run_stops_a_lane_on_quota_while_the_other_lane_continues_then_resumes(tmp_path, monkeypatch):
    farm = Farm(tmp_path, FOUR, monkeypatch)
    assert run_images(farm.plan_args(procs=1))[0] == 0  # acct1: B1, B3; acct2: B2, B4
    flag = farm.home("acct1") / "quota.flag"
    flag.write_text("You've hit your usage limit. Try again in 2 hours.", encoding="utf-8")
    code, out = farm.run()
    assert code == 4 and "acct1" in out["error"] and "quota" in out["error"], out
    status = status_file(farm)
    lanes = {l["label"]: l for l in status["lanes"]}
    assert lanes["acct1"]["state"] == "stopped" and lanes["acct1"]["reason"] == "quota"
    assert [b["state"] for b in lanes["acct1"]["batches"]] == ["failed", "pending"]  # B3 was never started
    assert lanes["acct2"]["state"] == "done" and lanes["acct2"]["images"] == 2
    assert len(farm.lib.calls("acct1")) == 1 and len(farm.lib.calls("acct2")) == 2  # no retry loop on the cooled account
    assert status["totals"] == {"wanted": 4, "done": 2, "remaining": 2}
    assert status["characters"] == {"CHAR_01": {"FACE": {"wanted": 1, "done": 0}, "ACTION": {"wanted": 1, "done": 1}},
                                    "CHAR_02": {"FACE": {"wanted": 1, "done": 0}, "ACTION": {"wanted": 1, "done": 1}}}
    assert "acct1" in pool.load_state(farm.state_path())["cooling"]
    flag.unlink()
    code, out = farm.run()  # still cooling in the shared state: the lane stops before any codex call, acct2 has nothing to do
    assert code == 4 and "cooling" in out["error"], out
    assert len(farm.lib.calls("acct1")) == 1
    assert {l["label"]: l["state"] for l in status_file(farm)["lanes"]} == {"acct1": "stopped", "acct2": "done"}
    pool.update_state(farm.state_path(), lambda s: pool.mark_good(s, "acct1"))
    code, out = farm.run()
    assert code == 0, out
    assert status_file(farm)["totals"] == {"wanted": 4, "done": 4, "remaining": 0} and len(farm.lib.calls("acct1")) == 3


def test_status_counts_before_and_after_a_run_and_measures_seconds_per_image(tmp_path, monkeypatch):
    farm = Farm(tmp_path, FOUR, monkeypatch)
    assert run_images(farm.plan_args(procs=1))[0] == 0
    empty = farm.status()
    assert empty["run_dir"] is None and empty["totals"] == {"wanted": 4, "done": 0, "remaining": 4} and empty["eta_seconds"] is None
    assert {l["state"] for l in empty["lanes"]} == {"pending"} and empty["lanes_active"] == 0
    assert farm.run()[0] == 0
    full = farm.status()
    assert full["totals"] == {"wanted": 4, "done": 4, "remaining": 0} and full["measured"]["images_timed"] == 4
    assert full["measured"]["seconds_per_image"] > 0 and full["eta_seconds"] is None  # nothing remaining, no lane active
    assert {l["state"] for l in full["lanes"]} == {"done"} and full["run_dir"] == library_status.latest_run_dir(farm.plan).resolve().as_posix()
    assert full["characters"]["CHAR_01"] == {"FACE": {"wanted": 1, "done": 1}, "ACTION": {"wanted": 1, "done": 1}}
    (farm.lib.lib_out / B2).rename(farm.lib.lib_out / "batch-02-gone")  # the receipt names an absolute PNG path: it is gone now
    assert farm.status()["totals"]["done"] == 3  # a take whose PNG vanished is not counted (resume would remake it)
    code, out = run_images(["library", "status", "--plan", str(farm.plan)])  # default output: JSON + a table on stderr
    assert code == 0 and out["totals"]["done"] == 3


def test_detached_run_refuses_a_second_run_while_a_lane_is_active(tmp_path, monkeypatch):
    farm = Farm(tmp_path, [(B1, "CHAR_01", "FACE", 1), (B3, "CHAR_02", "FACE", 1)], monkeypatch)
    monkeypatch.setenv("FAKE_CODEX_SLEEP", "2")
    assert run_images(farm.plan_args(accounts="acct1", procs=1))[0] == 0
    code, out = farm.run("--detach")
    assert code == 0 and out["detached"] and list(out["pids"]) == ["acct1"], out
    run_dir = Path(out["run_dir"])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not library_status.lane_active(run_dir, "acct1"):
        time.sleep(0.1)
    assert library_status.lane_active(run_dir, "acct1")
    code, again = farm.run()
    assert code == 1 and "active" in again["error"], again
    while time.monotonic() < deadline + 60 and library_status.lane_active(run_dir, "acct1"):
        time.sleep(0.2)
    assert not library_status.lane_active(run_dir, "acct1")
    final = farm.status()
    assert final["lanes"][0]["state"] == "done" and final["totals"]["done"] == 2 and final["measured"]["seconds_per_image"] >= 2.0


# --- units ----------------------------------------------------------------------------------------------------

def test_classify_failure_names_quota_auth_cooling_timeout_refused():
    quota = Uncertain("no codex account could make the image", evidence={"failovers": [{"label": "a", "outcome": "quota"}]})
    auth = Uncertain("no codex account", evidence={"failovers": [{"label": "a", "outcome": "no_auth_file"}]})
    cooling = Uncertain("every codex account is cooling: {'a': 1.0}; no job was started")
    timeout = Uncertain("codex exec exceeded 900 s on account a; the image may exist")
    assert [library_run.classify_failure(e) for e in (quota, auth, cooling, timeout, Refused("x"), Uncertain("y"), ValueError("z"))] == [
        "quota", "auth", "cooling", "timeout", "refused", "uncertain", "error"]


# --- khoá khung (P2-CANVAS) -------------------------------------------------------------------------------------

def _set_text(farm: Farm, index: int, text: str) -> str:
    row = farm.rows[index]
    for path in (farm.lib.tmp / f"{row['batch_id']}.json", farm.queue.parent / f"{row['batch_id']}.json"):  # both copies
        data = json.loads(path.read_text("utf-8"))
        data[0]["prompt_text"] = text
        path.write_text(json.dumps(data), encoding="utf-8")
    row["prompt_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    farm.write_queue()
    return row["prompt_id"]


def test_plan_refuses_a_16x9_or_unstated_aspect_naming_the_prompt_ids_and_accepts_3x4(tmp_path):
    farm = Farm(tmp_path, FOUR)
    wide = _set_text(farm, 0, "FACE r005c. 16:9 widescreen cinematic frame.")
    none = _set_text(farm, 1, "ACTION r005c. A waving worker, no frame stated.")
    code, out = run_images(farm.plan_args())
    assert code != 0 and not farm.plan.exists()
    assert wide in str(out) and none in str(out) and "16:9" in str(out) and "does not state 3:4" in str(out)
    _set_text(farm, 0, "FACE r005c. 3:4 vertical portrait, head and shoulders.")
    _set_text(farm, 1, "ACTION r005d. 3:4 vertical portrait, full body.")
    code, out = run_images(farm.plan_args())
    assert code == 0, out
    assert json.loads(farm.plan.read_text("utf-8"))["canvas"] == {"FACE": "3:4", "ACTION": "3:4"}


def test_status_flags_a_done_take_whose_png_header_is_not_3x4(tmp_path):
    from images_library_fixtures import png_bytes
    good, bad = tmp_path / "good.png", tmp_path / "bad.png"
    good.write_bytes(png_bytes(1536, 2048))
    bad.write_bytes(png_bytes(1672, 940))
    plan = {"canvas": {"FACE": "3:4", "ACTION": "3:4"}, "batches": {"b": {"items": [
        {"prompt_id": "CHAR_01_FACE_1", "kind": "FACE"}, {"prompt_id": "CHAR_01_ACTION_1", "kind": "ACTION"}]}}}
    done = {"CHAR_01_FACE_1": {"png": str(good)}, "CHAR_01_ACTION_1": {"png": str(bad)}}
    assert library_status.canvas_flags(plan, done) == [
        {"prompt_id": "CHAR_01_ACTION_1", "kind": "ACTION", "size": [1672, 940], "expected": "3:4"}]

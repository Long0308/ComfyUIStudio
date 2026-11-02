"""N23-fix: --prompt-batch library mode (no guide, no shot, no plan: Image 1 is the first ref), ref path safety,
prompt_text vs the queue's prompt_sha256, the provenance flag as DATA. FAKE codex only."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.images import codex, pool
from images_fixtures import LIVE, CARTOON, World, make_png, python_cmd, run_images
from engine.layout.context import domain_policy
from test_images_codex import FAKE, SECRET, Setup
from test_images_codex_batch import write_batch

REAL_DIR = Path(r"J:\1.JennieHomeSchool\03 Voice\production-local\engine\staging\newtecons-30s\image-batches")
REAL_EPISODE = Path(r"J:\1.JennieHomeSchool\03 Voice\production-local\JennieJoyKids-Story\Newtecons-TienDo-KichTinh-30s\engine\episode.json")
REF_NAMES = ("face.png", "vest.png", "logo.png")


class Lib:
    """A NEWTECONS-domain world with NO images-plan, 2 fake codex accounts and refs under tmp (an allowed root)."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.world = World(tmp, domain=LIVE)
        self.accounts = []
        for i in (1, 2):
            home = tmp / "homes" / f"acct{i}"
            home.mkdir(parents=True)
            (home / "auth.json").write_text(SECRET, encoding="utf-8")
            self.accounts.append(pool.Account(f"acct{i}", home))
        self.world.machine["images"] = {"batch_ref_roots": [str(tmp)], "codex_bin": python_cmd(FAKE), "codex_accounts": [
            {"label": a.label, "codex_home": str(a.codex_home)} for a in self.accounts]}
        self.world.write_machine()
        self.png = make_png(tmp / "fake-image.png", (10, 20, 30), (320, 180))
        import os
        self.env = {**os.environ, "FAKE_CODEX_PNG": str(self.png)}
        self.state, self.lib_out = tmp / "pool-state.json", tmp / "library"
        self.refs = [make_png(tmp / "refs" / n, (i * 40, 9, 9), (64, 64)) for i, n in enumerate(REF_NAMES, 1)]

    def batch_file(self, name: str = "libb", count: int = 2, *, order=None, queue: bool = False, queue_sha=None,
                   id_prefix: str | None = None, auto_queue: bool = True) -> Path:
        refs = [self.refs[i] for i in (order or range(3))]
        items = []
        for k in range(count):
            lines = "\n".join(f"Image{i}: {r.name}; role{i}; SHA256 {hashlib.sha256(r.read_bytes()).hexdigest()}"
                              for i, r in enumerate(self.refs, 1))
            text = f"PURPOSE: item {k + 1}.\r\nREFERENCES:\r\n{lines}\r\nUse Image1 as the sole facial identity. 3:4 vertical portrait.\r\n"
            items.append({"prompt_id": f"{id_prefix or name}_{k + 1}_r005", "prompt_text": text,
                          "ref_images": [{"path": str(r), "role": f"role{self.refs.index(r) + 1}",
                                          "sha256": hashlib.sha256(r.read_bytes()).hexdigest()} for r in refs]})
        path = self.tmp / f"{name}.json"
        path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        sha = lambda it: queue_sha or hashlib.sha256(it["prompt_text"].encode("utf-8")).hexdigest()  # noqa: E731
        if queue:
            rows = [{"prompt_id": it["prompt_id"], "prompt_sha256": sha(it), "dispatch_allowed": True, "domain": LIVE} for it in items]
            (self.tmp / "queue-r005.json").write_text(json.dumps(rows), encoding="utf-8")
        elif auto_queue:
            # N52c: NEWTECONS refuses a real submit without a queue; one merged boolean-true queue (no duplicate ids across batches)
            qfile = self.tmp / "queue-lib.json"
            old = json.loads(qfile.read_text("utf-8")) if qfile.exists() else []
            mine = {it["prompt_id"] for it in items}
            rows = [r for r in old if r["prompt_id"] not in mine]
            rows += [{"prompt_id": it["prompt_id"], "prompt_sha256": sha(it), "dispatch_allowed": True, "domain": LIVE} for it in items]
            qfile.write_text(json.dumps(rows), encoding="utf-8")
        return path

    def run(self, path: Path, **kw):
        return codex.submit_library_batch(self.world.ctx(), self.lib_out, path, self.accounts, codex_cmd=python_cmd(FAKE),
                                          state_path=self.state, base_env=self.env, timeout=30, **kw)

    def calls(self, label: str) -> list[dict]:
        log = next(a for a in self.accounts if a.label == label).codex_home / "calls.jsonl"
        return [json.loads(x) for x in log.read_text("utf-8").splitlines()] if log.exists() else []


def images_in(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]


def test_library_brief_image_numbers_match_the_real_dash_i_order_line_by_line(tmp_path):
    lib = Lib(tmp_path)
    result = lib.run(lib.batch_file(count=2))
    assert result["n"] == 2 and result["library"] is True and len(result["takes"]) == 2
    call = lib.calls("acct1")[0]
    sent = images_in(call["argv"])
    assert [Path(p).name for p in sent] == list(REF_NAMES)  # no guide: exactly the three refs
    stdin = call["stdin"]
    brief_lines = re.findall(r"(?m)^Image(\d+): ([^;]+);", stdin)
    assert [(int(n), name) for n, name in brief_lines] == [(1, "face.png"), (2, "vest.png"), (3, "logo.png")]
    for number, name in brief_lines:
        assert Path(sent[int(number) - 1]).name == name, (number, name)
    preface = re.findall(r"(?m)^Image (\d+): .*\[([^\]]+)\]", stdin)  # the engine's own role lines, numbered from 1
    assert [(int(n), name) for n, name in preface] == [(1, "face.png"), (2, "vest.png"), (3, "logo.png")]
    assert "layout/spatial guide" not in stdin and "PLACEMENT" not in stdin


def test_library_needs_no_plan_no_shot_and_writes_a_receipt_with_batch_and_prompt_id(tmp_path):
    lib = Lib(tmp_path)
    result = lib.run(lib.batch_file(count=2))
    assert not (tmp_path / "images").exists()
    takes = [Path(t["receipt"]).parent for t in result["takes"]]
    assert [p.name for p in takes] == ["t001", "t002"] and all(p.parent == lib.lib_out / "libb" for p in takes)
    for i, row in enumerate(result["takes"], 1):
        receipt = json.loads(Path(row["receipt"]).read_text("utf-8"))
        assert receipt["batch_id"] == "libb" and receipt["prompt_id"] == f"libb_{i}_r005" and "shot" not in receipt
        assert receipt["prompt_sha256"] and [r["role"] for r in receipt["ref_hashes"]] == ["role1", "role2", "role3"]
        assert Path(receipt["output"]["path"]).is_file() and receipt["output"]["sha256"] == row["candidate_sha256"]
        assert SECRET not in json.dumps(receipt)


def test_library_brief_that_disagrees_with_the_ref_order_is_refused_before_any_folder(tmp_path):
    lib = Lib(tmp_path)
    path = lib.batch_file(order=[1, 0, 2])  # refs listed vest, face, logo but the brief says Image1 = face
    with pytest.raises(Refused, match="Image1"):
        lib.run(path, dry_run=True)
    assert not lib.lib_out.exists()


def test_library_dry_run_plans_ten_takes_and_writes_nothing(tmp_path):
    lib = Lib(tmp_path)
    result = lib.run(lib.batch_file(count=10), dry_run=True)
    assert [t["take"] for t in result["takes"]] == [f"t{i:03d}" for i in range(1, 11)]
    assert result["dry_run"] and not lib.lib_out.exists() and not lib.state.exists() and not lib.calls("acct1")


@pytest.mark.parametrize("make_ref", ["auth", "codex_png", "outside", "relative", "txt"])
def test_ref_path_safety(tmp_path, make_ref):
    lib = Lib(tmp_path)
    path = lib.batch_file(count=1)
    items = json.loads(path.read_text("utf-8"))
    home = lib.accounts[0].codex_home
    bad = {"auth": home / "auth.json", "codex_png": make_png(home / "generated_images" / "s" / "x.png", (1, 1, 1), (8, 8)),
           "outside": make_png(tmp_path.parent / f"{tmp_path.name}-outside.png", (1, 1, 1), (8, 8)),
           "relative": Path("refs") / "face.png", "txt": tmp_path / "refs" / "notes.txt"}[make_ref]
    if make_ref == "txt":
        bad.write_text("x", encoding="utf-8")
    items[0]["ref_images"][0] = {"path": str(bad), "role": "role1"}
    path.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(Refused, match="reference"):
        lib.run(path, dry_run=True)
    assert not lib.lib_out.exists()


def test_ref_safety_also_applies_to_the_shot_mode_batch(tmp_path):
    setup = Setup(tmp_path)
    path = write_batch(tmp_path, "shotmode", 1)
    with pytest.raises(Refused, match="reference"):  # tmp is not an allowed root unless the machine lists it
        codex.submit_batch(setup.world.ctx(), setup.out, "S01_A", path, setup.accounts, codex_cmd=python_cmd(FAKE),
                           state_path=setup.state, base_env=setup.env, timeout=30, dry_run=True)


def test_prompt_text_must_match_the_queue_prompt_sha256(tmp_path):
    lib = Lib(tmp_path)
    good = lib.batch_file("q1", queue=True)
    assert lib.run(good, dry_run=True)["n"] == 2
    bad = lib.batch_file("q2", queue=True, queue_sha="0" * 64)
    with pytest.raises(Refused, match="prompt_sha256"):
        lib.run(bad, dry_run=True)
    path = lib.batch_file("q3")
    items = json.loads(path.read_text("utf-8"))
    items[1]["prompt_sha256"] = "f" * 64
    path.write_text(json.dumps(items), encoding="utf-8")
    (tmp_path / "queue-r005.json").unlink()
    with pytest.raises(Refused, match="prompt_sha256"):
        lib.run(path, dry_run=True)


def _write_queue(lib: Lib, path: Path, **extra) -> None:
    items = json.loads(path.read_text("utf-8"))
    rows = [{"prompt_id": it["prompt_id"], "prompt_sha256": hashlib.sha256(it["prompt_text"].encode("utf-8")).hexdigest(),
             "domain": LIVE, **extra}
            for it in items]
    (lib.tmp / "queue-r005.json").write_text(json.dumps(rows), encoding="utf-8")


def test_n52_queue_is_authority_item_sha_differing_from_queue_is_refused(tmp_path):
    lib = Lib(tmp_path)
    path = lib.batch_file("a1", count=1, queue=True, queue_sha="0" * 64)
    items = json.loads(path.read_text("utf-8"))
    items[0]["prompt_sha256"] = hashlib.sha256(items[0]["prompt_text"].encode("utf-8")).hexdigest()  # self-consistent item
    path.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(Refused, match="queue"):
        lib.run(path, dry_run=True)


def test_n52_corrupt_queue_is_refused_not_skipped(tmp_path):
    lib = Lib(tmp_path)
    path = lib.batch_file("a2", count=1)
    (tmp_path / "queue-r005.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(Refused, match="queue-r005.json"):
        lib.run(path, dry_run=True)
    (tmp_path / "queue-r005.json").write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(Refused, match="array"):
        lib.run(path, dry_run=True)


def test_n52_dispatch_false_refuses_real_submit_before_codex_but_dry_run_plans_it(tmp_path):
    lib = Lib(tmp_path)
    path = lib.batch_file("a3", count=2, auto_queue=False)
    _write_queue(lib, path, dispatch_allowed=False, status="BLOCKED_TEST")
    dry = lib.run(path, dry_run=True)
    assert dry["n"] == 2 and all(t["dispatch_allowed"] is False for t in dry["takes"])
    with pytest.raises(Refused, match="dispatch_allowed:false"):
        lib.run(path)
    assert not lib.lib_out.exists() and not lib.state.exists() and not lib.calls("acct1") and not lib.calls("acct2")


def test_n52_dispatch_true_or_no_queue_still_runs(tmp_path):
    lib = Lib(tmp_path)
    path = lib.batch_file("a4", count=1, auto_queue=False)
    assert lib.run(path, dry_run=True)["takes"][0]["dispatch_allowed"] is None  # no queue: old behaviour
    _write_queue(lib, path, dispatch_allowed=True)
    assert lib.run(path)["n"] == 1


def test_provenance_is_a_data_flag_in_the_routes_recipe(tmp_path):
    assert domain_policy(World(tmp_path / "a", domain=LIVE).ctx()).get("provenance_required") is True
    assert not domain_policy(World(tmp_path / "b", domain=CARTOON).ctx()).get("provenance_required")


def lib_cli(lib: Lib, *extra: str) -> list[str]:
    return ["submit", "--episode", str(lib.world.root), "--out", str(lib.tmp / "images"), "--machine", str(lib.world.machine_path),
            "--provider", "codex-exec", "--dry-run", *extra]


def test_cli_library_mode_dry_run_without_shot_or_plan_and_its_forbidden_combinations(tmp_path):
    lib = Lib(tmp_path)
    path = lib.batch_file(count=3)
    code, summary = run_images(lib_cli(lib, "--prompt-batch", str(path), "--library-out", str(lib.lib_out)))
    assert code == 0 and summary["n"] == 3 and summary["library"] is True and not lib.lib_out.exists()
    for extra in (["--shot", "S01_A"], ["--n", "2"], ["--take", "t1"]):
        code, _ = run_images(lib_cli(lib, "--prompt-batch", str(path), "--library-out", str(lib.lib_out), *extra))
        assert code == 1, extra
    code, _ = run_images(lib_cli(lib, "--prompt-file", str(path), "--library-out", str(lib.lib_out)))
    assert code == 1  # --library-out needs --prompt-batch
    code, _ = run_images(lib_cli(lib, "--prompt-batch", str(path)))
    assert code == 1  # without --library-out a shot is required


@pytest.mark.skipif(not (REAL_DIR.is_dir() and REAL_EPISODE.is_file()), reason="N27 files / NEWTECONS episode not present")
def test_real_cli_dry_run_on_batch_03_with_the_newtecons_episode_exits_0(tmp_path):
    batch_file = REAL_DIR / "batch-03-CHAR_01-FACE.json"
    code, summary = run_images(["submit", "--episode", str(REAL_EPISODE), "--out", str(tmp_path / "o"), "--provider", "codex-exec",
                                "--prompt-batch", str(batch_file), "--library-out", str(tmp_path / "lib"), "--dry-run"])
    assert code == 0, summary
    assert summary["n"] == 10 and summary["batch_id"] == batch_file.stem
    argv = summary["takes"][0]["argv_without_prompt"]
    names = [Path(p).name for p in images_in(argv)]
    items = json.loads(batch_file.read_text("utf-8"))
    brief_names = [m[1] for m in re.findall(r"(?m)^Image(\d+): ([^;]+);", items[0]["prompt_text"])]
    assert names == brief_names and len(names) == len(items[0]["ref_images"]) >= 12
    assert not (tmp_path / "lib").exists()

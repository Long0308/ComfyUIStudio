"""``jjv plan explain`` CLI: JSON on stdout, table on stderr, exit codes, exclusive --json-out, registration, hygiene."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import test_plan_support as S
from engine.plan import cli
from test_plan_support import base_config, mix_plan, mutate, record, shot_of, write_version

SKILL = Path(__file__).resolve().parents[1]


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    def core(config: dict) -> None:
        shot_of(config, "S01_B")["segments"][0]["sha256"] = S.sha("clip-v2")

    return (write_version(tmp_path, "old", base_config(), plan=mix_plan(), record=record()),
            write_version(tmp_path, "new", mutate(base_config(), core), plan=mix_plan(), record=record()))


def test_main_prints_json_on_stdout_and_the_human_table_on_stderr(tmp_path: Path, capsys) -> None:
    old, new = _dirs(tmp_path)
    assert cli.main(["explain", "--old", str(old), "--new", str(new)]) == 0
    out, err = capsys.readouterr()
    doc = json.loads(out)
    assert doc["ok"] is True and doc["summary"]["gpu_jobs_need_approval"] == ["motion.h3[S01_B]"]
    assert err.startswith("NODE") and "TOTAL" in err and "GPU job -- NEVER AUTO, needs approval" in err
    assert "motion.h3 x2" in err and "composite.segment x" in err           # unchanged rows are folded
    cli.main(["explain", "--old", str(old), "--new", str(new), "--verbose", "--no-table"])
    out, err = capsys.readouterr()
    assert err == "" and json.loads(out)["schema"] == "jjv/plan-explain/v1"
    cli.main(["explain", "--old", str(old), "--new", str(new), "--verbose"])
    assert "composite.segment[intro]" in capsys.readouterr().err


def test_json_out_is_exclusive_and_equals_stdout(tmp_path: Path, capsys) -> None:
    old, new = _dirs(tmp_path)
    target = tmp_path / "out" / "plan.json"
    argv = ["explain", "--old", str(old), "--new", str(new), "--json-out", str(target), "--no-table"]
    assert cli.main(argv) == 0
    assert json.loads(target.read_text("utf-8")) == json.loads(capsys.readouterr().out)
    assert cli.main(argv) == 1                       # never replaces an existing file
    assert "refusing to overwrite" in capsys.readouterr().out


def test_exit_codes_one_for_a_refusal_two_for_unreadable_input(tmp_path: Path, capsys) -> None:
    old, new = _dirs(tmp_path)
    assert cli.main(["explain", "--old", str(tmp_path / "nope"), "--new", str(new)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    (new / "config" / "review-config-x.json").write_text("{not json", encoding="utf-8")
    assert cli.main(["explain", "--old", str(old), "--new", str(new)]) == 2
    assert "cannot read JSON" in capsys.readouterr().out
    assert cli.main(["explain", "--old", str(old), "--new", str(old), "--costs", str(tmp_path / "missing.json")]) == 2


def test_register_cli_plugs_into_a_jjv_style_parser(tmp_path: Path, capsys) -> None:
    old, new = _dirs(tmp_path)
    parser = argparse.ArgumentParser(prog="jjv")
    cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    args = parser.parse_args(["plan", "explain", "--old", str(old), "--new", str(new), "--target", "all", "--no-table"])
    assert (args.stage, args.verb, args.target) == ("plan", "explain", "all")
    assert cli.run_plan(args) == 0
    assert json.loads(capsys.readouterr().out)["target"] == "all"


def test_standalone_entry_runs_under_python_dash_i(tmp_path: Path) -> None:
    old, new = _dirs(tmp_path)
    done = subprocess.run([sys.executable, "-I", str(SKILL / "engine" / "plan" / "__main__.py"), "explain", "--old", str(old),
                           "--new", str(new), "--no-table"], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["summary"]["est_seconds_gpu"] == 180.0


def test_the_plan_package_is_small_neutral_offline_and_has_no_job_runner() -> None:
    files = sorted((SKILL / "engine" / "plan").glob("*.py"))
    assert len(files) >= 9
    for source in files:
        text = source.read_text(encoding="utf-8")
        assert len(text.splitlines()) < 400, source
        low = text.lower()
        for token in ("jenniejoy", "newtecons", "04-milk-and-mom", "ep04", "8188", "d:\\", "socket", "urllib", "requests",
                      "subprocess", "http.client", ".post(", "os.system", "popen"):
            assert token not in low, (source.name, token)
    for source in sorted((SKILL / "tests").glob("test_plan_*.py")):
        assert len(source.read_text(encoding="utf-8").splitlines()) < 400, source

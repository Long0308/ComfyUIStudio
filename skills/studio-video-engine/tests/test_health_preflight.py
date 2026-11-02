"""T-E39 health preflight: six read-only checks, the dry (fixture) and live (fake ComfyUI) forms, the CLI verb."""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.comfy import docker_probe, guards
from engine.comfy.client import ComfyClient
from engine.core.errors import Refused, Uncertain
from engine.health import cli as health_cli
from engine.health import docker_facts, fixture, preflight
from fake_comfy import FakeComfy

CONTAINER = "render-box"
URL = "http://127.0.0.1:1"
CLASSES = ("KSampler", "Krea2EditModelPatch", "SaveImage")  # sorted, as graph_class_types returns them
GRAPH = {"1": {"class_type": "KSampler", "inputs": {}}, "2": {"class_type": "Krea2EditModelPatch", "inputs": {}},
         "3": {"class_type": "SaveImage", "inputs": {}}}


def healthy(**changes):
    return fixture.healthy_fixture(CONTAINER, CLASSES, **changes)


def dry(doc, **kw):
    kw.setdefault("graph", GRAPH)
    kw.setdefault("min_free_vram_mib", 4096)
    return preflight.dry_preflight(doc, container=CONTAINER, base_url=URL, **kw)


def check(report, name):
    return next(c for c in report.checks if c.name == name)


def boom(what):
    def raise_it(*args, **kwargs):
        raise AssertionError(what)
    return raise_it


def test_all_good_fixture_is_ready_with_six_ok_checks_and_nothing_queued():
    report = dry(healthy())
    assert report.ready and report.mode == "dry" and [c.name for c in report.checks] == list(preflight.CHECK_NAMES)
    assert all(c.ok and not c.skipped for c in report.checks) and report.failed == [] and report.problems == []
    doc = report.to_json()
    assert doc["schema"] == preflight.SCHEMA and doc["queued"] is False and doc["classes"] == list(CLASSES)
    assert check(report, "vram_free").detail["free_mib"] == 12288
    assert check(report, "queue_idle").detail == {"running": 0, "pending": 0}
    assert check(report, "container_identity").detail["args"] == ["main.py", "--disable-partner-nodes"]
    assert check(report, "docker_engine").detail["commands"][0] == "docker version --format {{.Server.Version}}"


def test_the_dry_form_runs_no_subprocess_no_http_and_never_posts(monkeypatch):
    monkeypatch.setattr(subprocess, "run", boom("subprocess in the dry form"))
    monkeypatch.setattr(docker_probe, "default_runner", boom("the real docker runner in the dry form"))
    monkeypatch.setattr(urllib.request, "urlopen", boom("HTTP in the dry form"))
    assert dry(healthy()).ready
    client = fixture.FixtureClient(healthy())
    with pytest.raises(AssertionError, match="never POSTs"):
        client.post("/prompt", {})


def test_queue_busy_refuses_names_the_counts_and_the_next_step():
    doc = healthy()
    doc["comfy"]["queue"] = {"queue_running": [[1, "p", {}, {"client_id": "x"}, []]], "queue_pending": [[2, "q", {}, {}, []]]}
    report = dry(doc)
    assert not report.ready and report.failed == ["queue_idle"]
    busy = check(report, "queue_idle")
    assert busy.detail["problem"] == "ComfyUI queue is busy (running=1, pending=1)" and "never interrupt" in busy.next_step
    assert report.problems == [f"queue_idle: ComfyUI queue is busy (running=1, pending=1) -> {busy.next_step}"]


def test_vram_below_the_recipe_minimum_refuses_and_exactly_the_minimum_passes():
    report = dry(healthy(vram_free_mib=8192), min_free_vram_mib=10240)
    assert report.failed == ["vram_free"]
    assert check(report, "vram_free").detail["problem"] == "free VRAM 8192 MiB < 10240 MiB minimum"
    assert "never frees memory" in check(report, "vram_free").next_step
    assert dry(healthy(vram_free_mib=10240), min_free_vram_mib=10240).ready
    doc = healthy()
    doc["comfy"]["system_stats"]["devices"] = []
    assert check(dry(doc), "vram_free").detail["problem"].startswith("GET /system_stats reports no device")


def test_two_devices_use_the_smallest_free_vram():
    doc = healthy()
    doc["comfy"]["system_stats"]["devices"].append({"name": "gpu-2", "vram_free": 1 << 30, "vram_total": 16 << 30})
    report = dry(doc, min_free_vram_mib=2048)
    assert report.failed == ["vram_free"] and check(report, "vram_free").detail["free_mib"] == 1024


def test_container_missing_disable_partner_nodes_refuses_with_the_flag_named():
    doc = healthy()
    doc["docker"]["containers"][CONTAINER]["args"] = ["main.py", "--listen"]
    report = dry(doc)
    assert report.failed == ["container_identity"]
    identity = check(report, "container_identity")
    assert "launched without --disable-partner-nodes" in identity.detail["problem"]
    assert "args: main.py --listen" in identity.detail["problem"]
    assert identity.next_step.startswith("operator: ") and "never starts, stops or restarts" in identity.next_step


def test_container_identity_also_needs_the_name_running_state_and_restart_policy():
    doc = healthy()
    doc["docker"]["containers"][CONTAINER].update(running=False, restart_policy="always")
    problem = check(dry(doc), "container_identity").detail["problem"]
    assert "not running" in problem and "restart policy 'always' != 'unless-stopped'" in problem
    other = healthy()
    other["docker"]["containers"] = {"other-box": other["docker"]["containers"][CONTAINER]}
    missing = check(dry(other), "container_identity")
    assert not missing.ok and "No such object: render-box" in missing.detail["problem"]


def test_the_live_process_argv_must_carry_the_flag_too():
    doc = healthy()
    doc["comfy"]["system_stats"]["system"]["argv"] = ["main.py"]
    report = dry(doc)
    assert report.failed == ["comfy_http"] and "lacks --disable-partner-nodes" in check(report, "comfy_http").detail["problem"]
    del doc["comfy"]["system_stats"]["system"]["argv"]  # a ComfyUI that reports no argv: the container facts decide
    assert dry(doc).ready and check(dry(doc), "comfy_http").detail["argv"] is None


def test_missing_custom_node_refuses_with_its_name_and_a_partner_node_refuses():
    doc = healthy()
    del doc["comfy"]["object_info"]["Krea2EditModelPatch"]
    report = dry(doc)
    assert report.failed == ["required_nodes"]
    nodes = check(report, "required_nodes")
    assert nodes.detail["classes"]["Krea2EditModelPatch"] == {"status": "missing"}
    assert nodes.detail["problem"] == "Krea2EditModelPatch: unknown to this ComfyUI (custom node missing or not whitelisted)"
    assert "install/whitelist" in nodes.next_step
    partner = healthy()
    partner["comfy"]["object_info"]["KSampler"] = {"python_module": "comfy_api_nodes.nodes_x", "category": "api node/image"}
    text = check(dry(partner), "required_nodes").detail["problem"]
    assert text.startswith("KSampler: partner/API node") and "never allowed" in text
    custom = healthy()
    custom["comfy"]["object_info"]["Krea2EditModelPatch"] = {"python_module": "custom_nodes.comfyui-krea2edit.nodes", "category": "x"}
    assert check(dry(custom), "required_nodes").detail["classes"]["Krea2EditModelPatch"]["pack"] == "comfyui-krea2edit"
    assert dry(healthy(), graph=None).ready and check(dry(healthy(), graph=None), "required_nodes").detail == {"classes": {}}


def test_docker_engine_unreachable_skips_container_identity_and_still_reports_comfy():
    doc = healthy()
    doc["docker"]["version"] = None
    report = dry(doc)
    assert report.failed == ["docker_engine", "container_identity"]
    engine = check(report, "docker_engine")
    assert "docker engine unreachable" in engine.detail["problem"] and "error during connect" in engine.detail["problem"]
    assert engine.next_step.startswith("operator: ") and "never starts it" in engine.next_step
    skipped = check(report, "container_identity")
    assert skipped.skipped and not skipped.ok and skipped.detail["problem"] == "not checked: docker engine unreachable"
    assert check(report, "queue_idle").ok and check(report, "vram_free").ok and check(report, "required_nodes").ok


def test_comfy_http_down_fails_and_skips_queue_vram_and_nodes():
    doc = healthy()
    doc["comfy"]["up"] = False
    report = dry(doc)
    assert report.failed == ["comfy_http", "queue_idle", "vram_free", "required_nodes"]
    http = check(report, "comfy_http")
    assert http.detail["problem"].startswith(f"ComfyUI HTTP down at {URL}") and "never restarts it" in http.next_step
    assert all(check(report, n).skipped for n in ("queue_idle", "vram_free", "required_nodes"))
    assert check(report, "docker_engine").ok and check(report, "container_identity").ok


def test_require_ready_raises_refused_with_the_report_as_evidence_and_returns_the_report_when_ready():
    doc = healthy()
    doc["comfy"]["queue"]["queue_running"] = [[1, "p", {}, {"client_id": "x"}, []]]
    target = SimpleNamespace(base_url=URL, container=CONTAINER)
    with pytest.raises(Refused, match=r"nothing was queued.*ComfyUI queue is busy \(running=1, pending=0\)") as caught:
        preflight.require_ready(fixture.FixtureClient(doc), target, graph=GRAPH, min_free_vram_mib=0,
                                runner=fixture.fixture_runner(doc))
    assert caught.value.exit_code == 1 and caught.value.evidence["stage"] == "health_preflight"
    assert caught.value.evidence["report"]["failed"] == ["queue_idle"]
    ok = preflight.require_ready(fixture.FixtureClient(healthy()), target, graph=GRAPH, min_free_vram_mib=0,
                                 runner=fixture.fixture_runner(healthy()))
    assert ok.ready and ok.mode == "live"


def test_live_collection_against_a_fake_comfyui_is_read_only_and_ready():
    with FakeComfy() as fake:
        client = ComfyClient(fake.url, timeout_seconds=5)
        target = SimpleNamespace(base_url=fake.url, container=CONTAINER)
        runner = fixture.fixture_runner(healthy())
        report = preflight.run_preflight(client, target, graph=GRAPH, min_free_vram_mib=4096, runner=runner)
        assert report.ready and report.mode == "live" and fake.posts_made() == []
        assert [p for _, p in fake.requests] == ["/system_stats", "/queue", "/object_info/KSampler",
                                                  "/object_info/Krea2EditModelPatch", "/object_info/SaveImage"]
        fake.unknown.add("Krea2EditModelPatch")
        fake.queue["queue_pending"] = [[2, "q", {}, {}, []]]
        again = preflight.run_preflight(client, target, graph=GRAPH, min_free_vram_mib=4096, runner=runner)
        assert again.failed == ["queue_idle", "required_nodes"] and fake.posts_made() == []


def test_a_dead_comfyui_port_is_a_named_check_not_an_exception():
    dead = "http://127.0.0.1:9"  # discard port: nothing listens
    client = ComfyClient(dead, timeout_seconds=1)
    report = preflight.run_preflight(client, SimpleNamespace(base_url=dead, container=CONTAINER), graph=GRAPH,
                                     min_free_vram_mib=0, runner=fixture.fixture_runner(healthy()))
    assert report.failed == ["comfy_http", "queue_idle", "vram_free", "required_nodes"]
    assert "GET /system_stats failed" in check(report, "comfy_http").detail["problem"]


def test_parse_inspect_line_accepts_the_docker_format_and_rejects_garbage():
    line = ('/render-box|true|2026-10-27T23:28:38.532695374Z|0|unless-stopped|'
            '["/opt/wrapper.py","main.py","--listen","0.0.0.0","--disable-partner-nodes"]\n')
    facts = docker_facts.parse_inspect_line(line)
    assert facts.name == "render-box" and facts.running and facts.restart_count == 0
    assert facts.restart_policy == "unless-stopped" and facts.started_at_text == "2026-10-27T23:28:38.532695374Z"
    assert "--disable-partner-nodes" in facts.args and facts.to_json()["args"][0] == "/opt/wrapper.py"
    for bad in ("", "a|b|c", "/x|true|t|0|no|not-json", '/x|true|t|0|no|{"a":1}', '/x|true|t|0|no|[1,2]'):
        with pytest.raises(ValueError):
            docker_facts.parse_inspect_line(bad)
    assert docker_facts.parse_inspect_line("/x|false|t|abc|no|[]").restart_count is None


def test_docker_runner_failures_become_text_never_exceptions():
    def missing(command):
        raise FileNotFoundError("docker")
    facts = docker_facts.collect_docker_facts(CONTAINER, runner=missing)
    assert not facts.engine_reachable and "could not run" in facts.engine_error and facts.container is None
    assert facts.container_error == "not checked: docker engine unreachable" and len(facts.commands) == 1

    def daemon_down(command):
        return subprocess.CompletedProcess(command, 1, "", "error during connect: cannot connect")
    assert "exit 1: error during connect" in docker_facts.collect_docker_facts(CONTAINER, runner=daemon_down).engine_error

    def no_such(command):
        if command[1] == "version":
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        return subprocess.CompletedProcess(command, 1, "", "Error: No such object: render-box")
    facts = docker_facts.collect_docker_facts(CONTAINER, runner=no_such)
    assert facts.engine_version == "28.0.0" and facts.container is None and "No such object" in facts.container_error

    def garbage(command):
        return subprocess.CompletedProcess(command, 0, "28.0.0\n" if command[1] == "version" else "nonsense\n", "")
    assert "expected 6" in docker_facts.collect_docker_facts(CONTAINER, runner=garbage).container_error

    def timeout(command):
        raise subprocess.TimeoutExpired(command, 60)
    assert "could not run" in docker_facts.collect_docker_facts(CONTAINER, runner=timeout).engine_error


def test_the_fixture_runner_only_answers_the_two_read_only_commands():
    run = fixture.fixture_runner(healthy())
    assert run(docker_facts.VERSION_COMMAND).stdout.strip() == "fixture"
    assert run(docker_facts.inspect_command(CONTAINER)).returncode == 0
    assert run(["docker", "restart", CONTAINER]).returncode == 2 and run(["docker", "stop", CONTAINER]).returncode == 2
    assert run(["docker", "inspect", CONTAINER]).returncode == 2  # only the exact read-only format is served


def test_partner_detection_agrees_with_the_dispatch_guards():
    samples = [{"python_module": "nodes"}, {"python_module": "comfy_api_nodes.nodes_x"}, {"api_node": True},
               {"category": "api node/video"}, {"category": "API Node/x"}, {"python_module": "custom_nodes.pack.x"}]
    assert [preflight._is_partner(s) for s in samples] == [guards._is_partner(s) for s in samples]
    assert sum(preflight._is_partner(s) for s in samples) == 4


def test_the_default_docker_runner_delegates_to_the_probe_runner_so_the_test_tripwire_applies(monkeypatch):
    seen = []
    monkeypatch.setattr(docker_probe, "default_runner",
                        lambda command: seen.append(command) or subprocess.CompletedProcess(command, 0, "x\n", ""))
    assert docker_facts._real_default_runner(["docker", "version"]).stdout == "x\n"
    assert seen == [["docker", "version"]]


def test_min_free_vram_must_be_a_non_negative_int():
    for bad in (-1, 1.5, True, "10"):
        with pytest.raises(ValueError):
            dry(healthy(), min_free_vram_mib=bad)


def test_load_fixture_rejects_a_foreign_document(tmp_path):
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(Uncertain, match="not a jjv/health-fixture/v1"):
        fixture.load_fixture(path)
    path.write_text(json.dumps({"schema": fixture.FIXTURE_SCHEMA, "docker": {}}), encoding="utf-8")
    with pytest.raises(Uncertain, match="'comfy'"):
        fixture.load_fixture(path)


def _run_cli(argv, capsys):
    parser = argparse.ArgumentParser()
    stages = parser.add_subparsers(dest="stage", required=True)
    health_cli.register_cli(stages)
    code = health_cli.run_health(parser.parse_args(argv))
    return code, json.loads(capsys.readouterr().out)


def test_cli_dry_preflight_from_a_fixture_file_exits_zero_ready_and_one_when_not(tmp_path, capsys):
    doc_path, graph_path = tmp_path / "fixture.json", tmp_path / "graph.api.json"
    doc_path.write_text(json.dumps(healthy()), encoding="utf-8")
    graph_path.write_text(json.dumps(GRAPH), encoding="utf-8")
    argv = ["health", "preflight", "--base-url", URL, "--container", CONTAINER, "--graph", str(graph_path),
            "--fixture", str(doc_path), "--min-free-vram-mib", "4096"]
    code, out = _run_cli(argv, capsys)
    assert code == 0 and out["ready"] and out["mode"] == "dry" and out["classes"] == list(CLASSES) and out["queued"] is False
    busy = healthy()
    busy["comfy"]["queue"]["queue_pending"] = [[2, "q", {}, {}, []]]
    doc_path.write_text(json.dumps(busy), encoding="utf-8")
    code, out = _run_cli(argv, capsys)
    assert code == 1 and out["failed"] == ["queue_idle"] and out["problems"][0].startswith("queue_idle: ComfyUI queue is busy")
    with pytest.raises(Refused, match="--episode"):
        _run_cli(["health", "preflight", "--fixture", str(doc_path)], capsys)
    with pytest.raises(Refused, match=">= 0"):
        _run_cli([*argv[:-1], "-5"], capsys)


def test_cli_resolves_the_machine_through_an_episode_and_stays_dry_with_a_fixture(tmp_path, capsys, monkeypatch):
    from engine.comfy.settings import settings_from_machine
    from engine.config.loader import resolve_episode

    settings = settings_from_machine(resolve_episode("04-milk-and-mom").machine)
    doc_path = tmp_path / "fixture.json"
    doc_path.write_text(json.dumps(fixture.healthy_fixture(settings.container)), encoding="utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", boom("no HTTP in the dry form"))
    monkeypatch.setattr(subprocess, "run", boom("no subprocess in the dry form"))
    code, out = _run_cli(["health", "preflight", "--episode", "04-milk-and-mom", "--fixture", str(doc_path)], capsys)
    assert code == 0 and out["container"] == settings.container and out["base_url"] == settings.base_url


def test_health_registers_next_to_every_existing_jjv_stage_without_a_name_clash():
    """The CLI-PATCH wires this registration into bin/jjv.py: prove it coexists with the real parser."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("jjv_bin_health", Path(__file__).resolve().parents[1] / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.build_parser()
    stages = next(a for a in parser._actions if a.dest == "stage")
    if "health" not in stages.choices:  # not wired yet: add it the way the patch does
        health_cli.register_cli(stages)
    args = parser.parse_args(["health", "preflight", "--episode", "e", "--graph", "g.json", "--min-free-vram-mib", "2048"])
    assert (args.stage, args.verb, args.min_free_vram_mib, args.fixture) == ("health", "preflight", 2048, None)

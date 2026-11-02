"""N92: quota belongs to a configured base account, including old per-lane state."""

from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.core.errors import Refused, Uncertain
from engine.images import codex, library_plan, pool


def accounts(*labels):
    return [pool.Account(label, Path("fake-homes") / label) for label in labels]


def state(**cooling):
    return {"schema": pool.STATE_SCHEMA, "last_good": None, "cooling": cooling, "history": []}


@pytest.mark.parametrize("source", ["acct3", "acct3b", "acct3c", "acct3d"])
def test_any_variant_cools_all_labels_of_its_base(source):
    configured = accounts("acct3", "acct3b", "acct3c", "acct3d", "acct4")
    saved = state(**{source: 200})
    live, cooling = pool.order(configured, saved, 100)
    assert [a.label for a in live] == ["acct4"]
    assert cooling == {label: 200 for label in ("acct3", "acct3b", "acct3c", "acct3d")}
    assert saved["cooling"] == {source: 200}  # old state is not rewritten by a read


def test_latest_unexpired_sibling_deadline_wins_even_when_sibling_is_not_selected():
    live, cooling = pool.order(accounts("acct3", "acct3b", "acct4"),
                               state(acct3=90, acct3b=150, acct3d="250"), 100)
    assert [a.label for a in live] == ["acct4"]
    assert cooling == {"acct3": 250, "acct3b": 250}


@pytest.mark.parametrize("labels,source,skipped", [
    (["acct3b", "acct3c"], "acct3b", ["acct3b"]),  # missing base: independent
    (["acct3", "acct3B", "acct30", "acct3bb"], "acct3", ["acct3"]),
    (["acct", "acctb", "acctbc"], "acctbc", ["acctbc"]),  # one removal, not recursive
    (["team", "teamb"], "team", ["team"]),  # N97: base không kết thúc bằng chữ số => hai tài khoản độc lập
    (["team1", "team1b"], "team1", ["team1", "team1b"]),  # không giới hạn ở tiền tố acct, miễn base kết thúc bằng chữ số
])
def test_suffix_rule_is_exact(labels, source, skipped):
    _, cooling = pool.order(accounts(*labels), state(**{source: 200}), 100)
    assert list(cooling) == skipped


def test_expired_cooling_keeps_original_sticky_order_and_independent_accounts():
    saved = state(acct3b=100, acct4=300)
    saved["last_good"] = "acct3c"
    live, cooling = pool.order(accounts("acct3", "acct3b", "acct3c", "acct4"), saved, 100)
    assert [a.label for a in live] == ["acct3c", "acct3", "acct3b"]
    assert cooling == {"acct4": 300}


def test_old_v1_file_loads_and_shares_its_variant_cooling(monkeypatch):
    saved = state(acct3d=200)
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(pool, "read_json", lambda path: saved)
    loaded = pool.load_state(Path("old-state.json"))
    assert loaded is saved
    assert pool.order(accounts("acct3", "acct3b"), loaded, 100)[1] == {"acct3": 200, "acct3b": 200}


@pytest.mark.parametrize("lane_label,source", [("acct3", "acct3d"), ("acct3b", "acct3d")])
def test_library_plan_refuses_cooling_outside_selected_lanes(monkeypatch, lane_label, source):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(pool, "load_state", lambda path: state(**{source: 200}))
    lanes = [{"label": label, "account": "acct3", "codex_home": "fake-home"}
             for label in ("acct3", lane_label)]
    with pytest.raises(Refused, match="cooling"):
        library_plan.refuse_cooling(Path("state.json"), lanes, 100)


def prepare_submit(monkeypatch, configured, saved):
    ctx = SimpleNamespace(machine={"images": {"codex_accounts": [
        {"label": label, "codex_home": "fake-home"} for label in configured]}})
    monkeypatch.setattr(codex, "require_provider", lambda *args: None)
    monkeypatch.setattr(codex, "domain_policy", lambda ctx: {})
    monkeypatch.setattr(pool, "load_state", lambda path: saved)
    monkeypatch.setattr(pool.Account, "auth_present", property(lambda self: True))
    item = {"batch_id": "batch", "prompt_id": "p", "batch_file": "batch.json", "ref_images": [],
            "prompt_text": "A test portrait."}
    return ctx, item


@pytest.mark.parametrize("pinned,configured", [(True, []), (False, ["acct3"])])
def test_submit_retains_base_context_for_pinned_and_cli_variant(monkeypatch, pinned, configured):
    ctx, item = prepare_submit(monkeypatch, configured, state(acct3d=200))
    selected = accounts("acct3", "acct3b") if pinned else accounts("acct3b")
    result = codex.submit(ctx, Path("out"), "shot", Path("prompt.txt"), selected,
                          codex_cmd=["fake-codex"], state_path=Path("state.json"),
                          recipe={"prompt_template": "{roles}\n{brief}"}, clock=lambda: 100,
                          account="acct3b", item=item, library_out=Path("library"), dry_run=True)
    assert result["account_order"] == []
    assert result["cooling"] == {"acct3b": 200}


@pytest.mark.parametrize("initial,expected_calls", [({"acct3d": 200}, []), ({}, ["acct3"])])
def test_post_lock_check_and_same_request_failover_skip_siblings(monkeypatch, initial, expected_calls):
    saved = state(**initial)
    ctx, _ = prepare_submit(monkeypatch, ["acct3", "acct3b"], saved)
    monkeypatch.setattr(pool, "locked", lambda *args, **kw: nullcontext())
    monkeypatch.setattr(codex, "write_json_once", lambda *args, **kw: None)
    calls = []

    def quota(*args):
        label = args[8].label
        calls.append(label)
        pool.mark_cooling(saved, label, 200, "quota", 100)
        args[-1].append({"label": label, "outcome": "quota"})
        return None

    monkeypatch.setattr(codex, "_try_account", quota)
    with pytest.raises(Uncertain):
        codex._run_pool(ctx, Path("out"), "shot", Path("folder"), [], "", {}, {},
                        accounts("acct3", "acct3b"), saved, Path("state.json"), {}, 30,
                        None, {}, lambda: 100, {}, ["fake-codex"])
    assert calls == expected_calls


def test_real_submit_keeps_cli_base_context_when_variant_cools_during_lock(monkeypatch):
    saved = state()
    ctx, item = prepare_submit(monkeypatch, [], saved)
    monkeypatch.setattr(codex, "_refuse_blocked", lambda *args, **kw: None)
    monkeypatch.setattr(codex, "claim_take", lambda *args: Path("fake-take"))
    monkeypatch.setattr(codex, "write_prompt", lambda *args: {"sha256": "fake-sha"})
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kw: None)
    monkeypatch.setattr(codex, "write_json_once", lambda *args, **kw: None)

    @contextmanager
    def cooled_while_queued(*args, **kw):
        pool.mark_cooling(saved, "acct3d", 200, "quota", 100)
        yield

    monkeypatch.setattr(pool, "locked", cooled_while_queued)
    monkeypatch.setattr(codex, "_try_account", lambda *args: pytest.fail("cooled sibling was submitted"))
    with pytest.raises(Uncertain) as error:
        codex.submit(ctx, Path("out"), "shot", Path("prompt.txt"), accounts("acct3", "acct3b"),
                     codex_cmd=["fake-codex"], state_path=Path("state.json"),
                     recipe={"prompt_template": "{roles}\n{brief}", "timeout_seconds": 30}, clock=lambda: 100,
                     account="acct3b", item=item, library_out=Path("library"))
    assert error.value.evidence["failovers"] == [
        {"label": "acct3b", "outcome": "cooling_after_lock", "cooling_until": 200}]


def test_build_plan_retains_configured_base_outside_selected_lanes(monkeypatch):
    machine = {"images": {"codex_accounts": [
        {"label": label, "codex_home": "fake-home"} for label in ("acct3", "acct3b")]}}
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr(library_plan, "read_json", lambda path: machine)
    monkeypatch.setattr(library_plan, "load_queue_rows", lambda *args: [{}])
    monkeypatch.setattr(library_plan, "library_canvas", lambda: {})
    monkeypatch.setattr(library_plan, "batches_from", lambda *args: {})
    monkeypatch.setattr(library_plan, "lanes_for", lambda *args: (
        [], [{"label": "acct3b", "account": "acct3b", "codex_home": "fake-home"}]))
    monkeypatch.setattr(pool, "load_state", lambda path: state(acct3d=200))
    monkeypatch.setattr(library_plan, "write_json_once", lambda *args, **kw: pytest.fail("cooling plan written"))
    with pytest.raises(Refused, match="cooling"):
        library_plan.build_plan(queue=Path("queue-r005.json"), accounts=["acct3b"], procs=1,
                                out=Path("plan.json"), machine_path="fake-machine.json",
                                pool_state="state.json", clock=lambda: 100)

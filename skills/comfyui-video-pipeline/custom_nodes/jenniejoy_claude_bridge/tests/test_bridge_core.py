from __future__ import annotations

import errno
import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from _jj_bridge_support import SECRET_TOKEN

H = "a" * 64


def _no_secret_on_disk(root: Path) -> None:
    for item in root.rglob("*"):
        if item.is_file():
            assert SECRET_TOKEN not in item.read_text(encoding="utf-8", errors="replace"), item


# ---------------------------------------------------------------- key / cache
def test_cache_key_matches_an_independent_computation(core: Any) -> None:
    payload = {
        "images": [H],
        "prompt": "p",
        "schema": "jj-claude-bridge/key-v1",
        "system": "s",
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert core.cache_key("s", "p", [H]) == expected


def test_cache_key_depends_only_on_system_prompt_images(core: Any) -> None:
    base = core.cache_key("s", "p", [])
    assert base == core.cache_key("s", "p", [])
    assert base != core.cache_key("s2", "p", [])
    assert base != core.cache_key("s", "p2", [])
    assert base != core.cache_key("s", "p", [H])
    assert core.cache_key("s", "p", [H, "b" * 64]) != core.cache_key("s", "p", ["b" * 64, H])


def test_key_ignores_mode_and_timeout(core: Any, paths: Any, gateway: Any, router_env: Any) -> None:
    first = core.resolve(paths, system="s", prompt="p", mode="router", timeout_s=30, env=router_env)
    again = core.resolve(paths, system="s", prompt="p", mode="cache_only", timeout_s=999, env={})
    assert first.key == again.key and again.cache_hit and not first.cache_hit


def test_cache_only_miss_is_loud(core: Any, paths: Any) -> None:
    with pytest.raises(core.CacheMiss, match="cache_only"):
        core.resolve(paths, system="", prompt="never asked", mode="cache_only", env={})


def test_replay_is_deterministic_and_calls_the_gateway_once(
    core: Any, paths: Any, gateway: Any, router_env: Any
) -> None:
    first = core.resolve(paths, system="sys", prompt="hello", mode="router", env=router_env)
    gateway.state.reply_text = "A DIFFERENT ANSWER"  # a second real call would differ
    second = core.resolve(paths, system="sys", prompt="hello", mode="auto", env=router_env)
    assert len(gateway.state.requests) == 1
    assert second.cache_hit is True and first.cache_hit is False
    assert second.answer == first.answer == "gateway answer"
    assert second.receipt_text == first.receipt_text
    assert second.receipt["route"] == "router"  # replay keeps the ORIGINAL route


def test_receipt_fields(core: Any, paths: Any, gateway: Any, router_env: Any) -> None:
    result = core.resolve(paths, system="s", prompt="p", mode="router", env=router_env)
    receipt = result.receipt
    assert receipt["route"] == "router" and receipt["mode_requested"] == "router"
    assert receipt["model_reported"] == "fake-claude-gateway"
    assert receipt["requested_model"] == "claude-via-gateway"
    assert receipt["request_sha256"] == hashlib.sha256(gateway.state.requests[0]["raw"]).hexdigest()
    assert len(receipt["response_sha256"]) == 64
    assert receipt["response_sha256_of_answer"] == hashlib.sha256(b"gateway answer").hexdigest()
    assert receipt["requested_at"] and receipt["answered_at"]
    assert receipt["gateway_host"].startswith("127.0.0.1:")
    assert SECRET_TOKEN not in json.dumps(receipt)


def test_corrupt_or_tampered_cache_is_refused_not_guessed(core: Any, paths: Any) -> None:
    key = core.cache_key("", "p", [])
    paths.ensure()
    target = paths.entry(paths.cache, key)
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(core.BridgeError, match="not readable JSON"):
        core.cache_get(paths, key)
    target.write_text(
        json.dumps({"schema": core.CACHE_SCHEMA, "key": key, "answer": "x",
                    "receipt": {"response_sha256_of_answer": "0" * 64}}),
        encoding="utf-8",
    )
    with pytest.raises(core.BridgeError, match="does not match"):
        core.cache_get(paths, key)


def test_cache_put_never_replaces_an_existing_entry(core: Any, paths: Any) -> None:
    key = core.cache_key("", "p", [])
    sha = lambda text: hashlib.sha256(text.encode()).hexdigest()  # noqa: E731
    first = core.cache_put(paths, key, "one", {"response_sha256_of_answer": sha("one")})
    second = core.cache_put(paths, key, "two", {"response_sha256_of_answer": sha("two")})
    assert first["answer"] == second["answer"] == "one"
    assert not list(paths.cache.glob("*.tmp"))


# ---------------------------------------------------------------- router
def test_router_chat_shape_and_token_only_in_header(
    core: Any, paths: Any, gateway: Any, router_env: Any
) -> None:
    core.resolve(paths, system="be brief", prompt="hi", mode="router", env=router_env)
    seen = gateway.state.requests[0]
    assert seen["path"] == "/v1/chat/completions"
    assert seen["authorization"] == f"Bearer {SECRET_TOKEN}"
    assert seen["body"]["model"] == "claude-via-gateway"
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]
    assert SECRET_TOKEN.encode() not in seen["raw"]
    _no_secret_on_disk(paths.base)


def test_router_base_url_ending_in_v1_is_not_doubled(core: Any) -> None:
    config = core.router_config(
        {"JJ_BRIDGE_BASE_URL": "http://host.docker.internal:1/v1/", "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": "t"}
    )
    assert config.endpoint == "http://host.docker.internal:1/v1/chat/completions"
    config = core.router_config(
        {"JJ_BRIDGE_BASE_URL": "https://gateway.example", "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": "t",
         "JJ_BRIDGE_API": "responses"}
    )
    assert config.endpoint == "https://gateway.example/v1/responses"


def test_router_responses_api_shape(core: Any, paths: Any, gateway: Any, router_env: Any) -> None:
    env = {**router_env, "JJ_BRIDGE_API": "responses"}
    result = core.resolve(paths, system="sys", prompt="hi", mode="router", env=env)
    seen = gateway.state.requests[0]
    assert seen["path"] == "/v1/responses"
    assert seen["body"]["instructions"] == "sys"
    assert seen["body"]["input"][0]["content"][0] == {"type": "input_text", "text": "hi"}
    assert result.answer == "gateway answer"


def test_router_sends_images_as_data_uris(core: Any, paths: Any, gateway: Any, router_env: Any) -> None:
    blob = core.ImageBlob("c" * 64, b"\x89PNG-fake")
    core.resolve(paths, system="", prompt="look", images=[blob], mode="router", env=router_env)
    content = gateway.state.requests[0]["body"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert paths.image("c" * 64).read_bytes() == b"\x89PNG-fake"  # saved beside the bridge


@pytest.mark.parametrize("status", [401, 500])
def test_router_http_error_is_loud_and_never_cached(
    core: Any, paths: Any, gateway: Any, router_env: Any, status: int
) -> None:
    gateway.state.status = status
    gateway.state.error_body = f"nope {SECRET_TOKEN}"  # a gateway echoing the token
    with pytest.raises(core.RouterError) as caught:
        core.resolve(paths, system="", prompt="p", mode="router", env=router_env)
    assert str(status) in str(caught.value)
    assert SECRET_TOKEN not in str(caught.value)
    assert not list(paths.cache.glob("*.json"))


def test_router_unreachable_is_a_router_error(core: Any, paths: Any) -> None:
    env = {"JJ_BRIDGE_BASE_URL": "http://127.0.0.1:1", "JJ_BRIDGE_MODEL": "m",
           "JJ_BRIDGE_TOKEN": SECRET_TOKEN}
    with pytest.raises(core.RouterError, match="unreachable") as caught:
        core.resolve(paths, system="", prompt="p", mode="router", env=env, timeout_s=3)
    assert SECRET_TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "env,match",
    [
        ({"JJ_BRIDGE_BASE_URL": "http://h"}, "half-configured"),
        ({"JJ_BRIDGE_BASE_URL": "ftp://h", "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": "t"}, "http"),
        ({"JJ_BRIDGE_BASE_URL": "http://u:p@h", "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": "t"},
         "credentials"),
        ({"JJ_BRIDGE_BASE_URL": "http://h?x=1", "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": "t"},
         "query"),
        ({"JJ_BRIDGE_BASE_URL": "http://h", "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": "t",
          "JJ_BRIDGE_API": "bogus"}, "JJ_BRIDGE_API"),
    ],
)
def test_router_misconfiguration_is_refused(core: Any, env: dict[str, str], match: str) -> None:
    with pytest.raises(core.RouterError, match=match):
        core.router_config(env)


def test_router_mode_without_config_is_an_error(core: Any, paths: Any) -> None:
    with pytest.raises(core.RouterError, match="JJ_BRIDGE_BASE_URL"):
        core.resolve(paths, system="", prompt="p", mode="router", env={})


def test_router_config_repr_hides_the_token(core: Any) -> None:
    config = core.router_config(
        {"JJ_BRIDGE_BASE_URL": "http://localhost", "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": SECRET_TOKEN}
    )
    assert SECRET_TOKEN not in repr(config)


# ---------------------------------------------------------------- heartbeat / auto
def test_heartbeat_age_boundaries(core: Any, paths: Any) -> None:
    assert core.heartbeat_age(paths) is None and not core.chat_is_live(paths)
    core.write_heartbeat(paths, "t", now=1000.0)
    assert core.chat_is_live(paths, now=1000.0 + 119.0)
    assert not core.chat_is_live(paths, now=1000.0 + 120.0)
    assert not core.chat_is_live(paths, now=1000.0 + 500.0)


def test_heartbeat_from_the_future_or_garbage_is_not_live(core: Any, paths: Any) -> None:
    core.write_heartbeat(paths, "t", now=5000.0)
    assert not core.chat_is_live(paths, now=5000.0 - 60.0)  # clock skew: cannot prove liveness
    assert core.chat_is_live(paths, now=5000.0 - 2.0)  # tiny skew tolerated
    paths.heartbeat.write_text("garbage", encoding="utf-8")
    assert core.heartbeat_age(paths, now=1.0) is None
    paths.heartbeat.write_text(json.dumps({"time_unix": "soon"}), encoding="utf-8")
    assert core.heartbeat_age(paths, now=1.0) is None


def test_auto_prefers_a_live_chat_and_never_touches_the_router(
    core: Any, paths: Any, gateway: Any, router_env: Any
) -> None:
    core.write_heartbeat(paths, "t")
    answered: dict[str, Any] = {}

    def serve() -> None:
        for _ in range(200):
            pending = core.list_pending(paths)
            if pending:
                answered["record"] = core.post_answer(
                    paths, pending[0]["request_id"], "from the chat", "claude-in-chat"
                )
                return
            threading.Event().wait(0.05)

    worker = threading.Thread(target=serve)
    worker.start()
    result = core.resolve(paths, system="s", prompt="q", mode="auto", env=router_env,
                          timeout_s=20, poll_s=0.05)
    worker.join()
    assert result.answer == "from the chat" and result.receipt["route"] == "chat"
    assert result.receipt["model_reported"] == "claude-in-chat"
    assert gateway.state.requests == []


def test_auto_with_stale_heartbeat_uses_the_router(
    core: Any, paths: Any, gateway: Any, router_env: Any
) -> None:
    core.write_heartbeat(paths, "t", now=1.0)  # 1970: long dead
    result = core.resolve(paths, system="", prompt="q", mode="auto", env=router_env)
    assert result.receipt["route"] == "router" and len(gateway.state.requests) == 1
    assert not list(paths.inbox.glob("*.json"))  # never queued for a chat that is not there


def test_auto_without_any_route_is_a_loud_error_and_sends_nothing(
    core: Any, paths: Any, gateway: Any
) -> None:
    with pytest.raises(core.NoRouteAvailable, match="no cloud fallback"):
        core.resolve(paths, system="", prompt="q", mode="auto", env={})
    assert gateway.state.requests == []
    assert not paths.inbox.exists() or not list(paths.inbox.glob("*.json"))


def test_a_chat_timeout_does_not_fall_back_to_the_router(
    core: Any, paths: Any, gateway: Any, router_env: Any
) -> None:
    core.write_heartbeat(paths, "t")
    with pytest.raises(core.ChatTimeout, match="still pending"):
        core.resolve(paths, system="", prompt="q", mode="auto", env=router_env,
                     timeout_s=1, poll_s=0.05)
    assert gateway.state.requests == []
    assert len(core.list_pending(paths)) == 1


def test_timed_out_request_can_be_answered_later_and_rerun_picks_it_up(
    core: Any, paths: Any
) -> None:
    with pytest.raises(core.ChatTimeout):
        core.resolve(paths, system="", prompt="slow", mode="chat", env={}, timeout_s=1, poll_s=0.05)
    (pending,) = core.list_pending(paths)
    core.post_answer(paths, pending["request_id"], "late but fine")
    result = core.resolve(paths, system="", prompt="slow", mode="chat", env={}, timeout_s=1)
    assert result.answer == "late but fine" and result.receipt["route"] == "chat"


def test_wait_for_answer_timeout_uses_the_injected_clock(core: Any, paths: Any) -> None:
    ticks = iter([0.0, 0.0, 5.0, 10.0, 20.0])
    slept: list[float] = []
    with pytest.raises(core.ChatTimeout):
        core.wait_for_answer(paths, "d" * 64, 10, 2.0, sleep=slept.append,
                             clock=lambda: next(ticks))
    assert slept == [2.0, 2.0]


def test_interrupt_hook_runs_while_waiting(core: Any, paths: Any) -> None:
    class Stop(Exception):
        pass

    def on_poll() -> None:
        raise Stop

    with pytest.raises(Stop):
        core.resolve(paths, system="", prompt="q", mode="chat", env={}, timeout_s=30,
                     on_poll=on_poll, poll_s=0.01)


# ---------------------------------------------------------------- inbox / outbox safety
def _queue(core: Any, paths: Any, prompt: str = "q") -> str:
    key = core.cache_key("", prompt, [])
    core.write_request(paths, key, "", prompt, [], 60)
    return key


def test_post_answer_refuses_unknown_ids(core: Any, paths: Any) -> None:
    paths.ensure()
    with pytest.raises(core.RefusedRequest, match="unknown request_id"):
        core.post_answer(paths, "e" * 64, "hello")
    assert not list(paths.outbox.glob("*.json"))


@pytest.mark.parametrize(
    "bad",
    ["../" + "e" * 61, "..\\..\\evil", "E" * 64, "e" * 63, "e" * 65, "", "a/b", "C:\\x",
     "e" * 64 + "/../../x", None, 12],
)
def test_post_answer_refuses_path_traversal_and_malformed_ids(core: Any, paths: Any, bad: Any) -> None:
    paths.ensure()
    with pytest.raises(core.RefusedRequest, match="request_id"):
        core.post_answer(paths, bad, "hello")
    outside = list(paths.base.parent.rglob("*.json"))
    assert outside == []


def test_post_answer_refuses_to_overwrite(core: Any, paths: Any) -> None:
    key = _queue(core, paths)
    core.post_answer(paths, key, "first")
    with pytest.raises(core.RefusedRequest, match="already answered"):
        core.post_answer(paths, key, "second")
    assert json.loads(paths.entry(paths.outbox, key).read_text("utf-8"))["answer"] == "first"
    assert not list(paths.outbox.glob("*.tmp"))


@pytest.mark.parametrize("answer", ["", "   ", None, 5, ["x"]])
def test_post_answer_refuses_bad_answers(core: Any, paths: Any, answer: Any) -> None:
    key = _queue(core, paths)
    with pytest.raises(core.RefusedRequest, match="non-empty string"):
        core.post_answer(paths, key, answer)


def test_post_answer_refuses_oversized_answers(core: Any, paths: Any) -> None:
    key = _queue(core, paths)
    with pytest.raises(core.RefusedRequest, match="exceeds"):
        core.post_answer(paths, key, "x" * (core.MAX_ANSWER_BYTES + 1))


def test_symlinked_inbox_entry_cannot_escape(core: Any, paths: Any, shared: Path) -> None:
    paths.ensure()
    secret = shared / "outside.json"
    secret.write_text("{}", encoding="utf-8")
    link = paths.inbox / ("f" * 64 + ".json")
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this Windows account")
    with pytest.raises(core.RefusedRequest, match="escapes"):
        core.post_answer(paths, "f" * 64, "hello")


def test_pending_listing_is_ordered_and_hides_answered(core: Any, paths: Any) -> None:
    first = _queue(core, paths, "one")
    second = _queue(core, paths, "two")
    assert {item["request_id"] for item in core.list_pending(paths)} == {first, second}
    core.post_answer(paths, first, "done")
    assert [item["request_id"] for item in core.list_pending(paths)] == [second]
    assert core.read_pending(paths, first)["answered"] is True
    with pytest.raises(core.RefusedRequest):
        core.read_pending(paths, "9" * 64)


def test_write_request_is_idempotent(core: Any, paths: Any) -> None:
    key = core.cache_key("", "q", [])
    one = core.write_request(paths, key, "", "q", [], 60)
    two = core.write_request(paths, key, "", "q", [], 999)
    assert one["created_unix"] == two["created_unix"] and two["timeout_s"] == 60


def test_malformed_or_misaddressed_answer_is_refused(core: Any, paths: Any) -> None:
    key = _queue(core, paths)
    paths.ensure()
    target = paths.entry(paths.outbox, key)
    target.write_text(json.dumps({"schema": core.ANSWER_SCHEMA, "request_id": "0" * 64,
                                  "answer": "x"}), encoding="utf-8")
    with pytest.raises(core.BridgeError, match="malformed or addressed elsewhere"):
        core.read_answer(paths, key)


def test_answers_can_hold_unicode(core: Any, paths: Any) -> None:
    key = core.cache_key("hệ thống", "Xin chào Jennie", [])
    core.write_request(paths, key, "hệ thống", "Xin chào Jennie", [], 60)
    core.post_answer(paths, key, "Đã rõ — tiếng Việt")
    result = core.resolve(paths, system="hệ thống", prompt="Xin chào Jennie", mode="chat",
                          env={}, timeout_s=5)
    assert result.answer == "Đã rõ — tiếng Việt"


# ---------------------------------------------------------------- misc
def test_default_shared_dir(core: Any, tmp_path_factory: Any) -> None:
    assert core.default_shared_dir({"JJ_BRIDGE_SHARED": "/x/y"}) == Path("/x/y")
    pack = Path("/opt/ComfyUI/custom_nodes/jenniejoy_claude_bridge")
    derived = core.default_shared_dir({}, pack)
    assert derived.name == "user" and derived.parent.name == "ComfyUI"
    with pytest.raises(core.BridgeError):
        core.default_shared_dir({})


@pytest.mark.parametrize("mode", ["", "AUTO", "cloud", None])
def test_invalid_mode_is_refused(core: Any, paths: Any, mode: Any) -> None:
    with pytest.raises(core.BridgeError, match="mode must be"):
        core.resolve(paths, system="", prompt="p", mode=mode, env={})


def test_empty_prompt_is_refused(core: Any, paths: Any) -> None:
    with pytest.raises(core.BridgeError, match="prompt must not be empty"):
        core.resolve(paths, system="", prompt="  ", mode="auto", env={})


def test_clamp_timeout(core: Any) -> None:
    assert core.clamp_timeout(None) == 600
    assert core.clamp_timeout("abc") == 600
    assert core.clamp_timeout(0) == 1
    assert core.clamp_timeout(10**9) == 86400
    assert core.clamp_timeout(30) == 30


# ---------------------------------------------------------------- links / junctions (no privilege needed)
def _make_link(target: Path, link: Path) -> None:
    """Directory junction on Windows (no admin rights), symlink elsewhere. Never skips."""
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        assert os.path.isjunction(link)
    else:
        link.symlink_to(target, target_is_directory=True)
        assert link.is_symlink()


@pytest.fixture
def outside(shared: Path) -> Path:
    folder = shared / "OUTSIDE"
    folder.mkdir()
    return folder


@pytest.mark.parametrize("name", ["inbox", "outbox", "cache", "images"])
def test_a_linked_subfolder_is_refused_everywhere_and_nothing_leaks(
    core: Any, paths: Any, outside: Path, name: str
) -> None:
    paths.base.mkdir(parents=True)
    _make_link(outside, paths.base / name)
    with pytest.raises(core.RefusedRequest, match="link/junction"):
        paths.ensure()
    key = core.cache_key("", "q", [])
    attempts = (
        lambda: core.write_request(paths, key, "", "q", [], 60),
        lambda: core.post_answer(paths, key, "a"),
        lambda: core.list_pending(paths),
        lambda: core.cache_get(paths, key),
        lambda: core.cache_put(paths, key, "a", {"response_sha256_of_answer": "0" * 64}),
        lambda: core.save_images(paths, [core.ImageBlob("a" * 64, b"x")]),
        lambda: core.read_answer(paths, key),
        lambda: core.resolve(paths, system="", prompt="q", mode="chat", env={}, timeout_s=1),
    )
    refused = 0
    for attempt in attempts:
        try:
            attempt()
        except core.RefusedRequest:
            refused += 1
        except core.BridgeError:
            pass  # an unrelated sub-folder was fine; this call just had nothing to do
    assert refused >= 1
    assert list(outside.iterdir()) == [], list(outside.iterdir())


def test_write_request_into_a_junctioned_inbox_writes_nothing_outside(
    core: Any, paths: Any, outside: Path
) -> None:
    paths.base.mkdir(parents=True)
    _make_link(outside, paths.base / "inbox")
    key = core.cache_key("", "q", [])
    with pytest.raises(core.RefusedRequest, match="link/junction"):
        core.write_request(paths, key, "", "q", [], 60)
    assert list(outside.iterdir()) == []


def test_a_linked_bridge_root_is_refused(core: Any, shared: Path, outside: Path) -> None:
    _make_link(outside, shared / "claude-bridge")
    paths = core.BridgePaths.from_shared(shared)
    with pytest.raises(core.RefusedRequest, match="link/junction"):
        paths.ensure()
    with pytest.raises(core.RefusedRequest, match="link/junction"):
        core.write_heartbeat(paths, "t")
    assert list(outside.iterdir()) == []


def test_a_linked_inbox_does_not_affect_the_heartbeat_file(core: Any, paths: Any, outside: Path) -> None:
    paths.base.mkdir(parents=True)
    _make_link(outside, paths.base / "inbox")
    core.write_heartbeat(paths, "t")
    assert core.chat_is_live(paths) and list(outside.iterdir()) == []


def test_a_nested_link_below_a_folder_is_refused(core: Any, paths: Any, outside: Path) -> None:
    paths.ensure()
    nested = paths.inbox / "nested"
    _make_link(outside, nested)
    with pytest.raises(core.RefusedRequest, match="link/junction"):
        paths.check(nested / ("a" * 64 + ".json"))


def test_pending_listing_survives_an_unparseable_entry(core: Any, paths: Any) -> None:
    key = _queue(core, paths, "ok")
    (paths.inbox / ("b" * 64 + ".json")).write_text("{broken", encoding="utf-8")
    listing = core.list_pending(paths)
    assert {item["request_id"] for item in listing} == {key, "b" * 64}
    assert [item for item in listing if "error" in item][0]["request_id"] == "b" * 64


@pytest.mark.parametrize("bad", ["oops", None, True, [1], {"a": 1}])
def test_pending_listing_survives_valid_json_with_a_bad_created_unix(core: Any, paths: Any, bad: Any) -> None:
    good = _queue(core, paths, "fine")
    (paths.inbox / ("c" * 64 + ".json")).write_text(
        json.dumps({"request_id": "c" * 64, "created_unix": bad, "prompt": "x"}), encoding="utf-8")
    listing = core.list_pending(paths)  # must not raise
    assert [item["request_id"] for item in listing if "error" not in item] == [good]
    broken = [item for item in listing if "error" in item]
    assert len(broken) == 1 and broken[0]["request_id"] == "c" * 64
    assert "created_unix" in broken[0]["error"]


# ---------------------------------------------------------------- atomic create / read hardening
def test_create_fallback_without_hard_links_is_exclusive_and_never_overwrites(
    core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_link(*args: Any, **kwargs: Any) -> None:
        raise OSError(errno.EPERM, "hard links unsupported")

    monkeypatch.setattr(core.os, "link", no_link)
    paths.ensure()
    target = paths.entry(paths.outbox, "c" * 64)
    assert core.atomic_create_json(target, {"v": 1}) is True
    assert core.atomic_create_json(target, {"v": 2}) is False
    assert json.loads(target.read_text("utf-8")) == {"v": 1}
    assert not list(paths.outbox.glob("*.tmp"))


def test_create_failure_while_writing_the_temp_leaves_no_temp_behind(
    core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.ensure()
    real = core._write_synced

    def flaky(target: Path, payload: bytes, exclusive: bool = False) -> None:
        real(target, payload[: len(payload) // 2], exclusive)
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(core, "_write_synced", flaky)
    with pytest.raises(OSError):
        core.atomic_create_json(paths.entry(paths.outbox, "d" * 64), {"v": 1})
    assert not list(paths.outbox.glob("*")), list(paths.outbox.glob("*"))


def test_unreadable_json_is_retried_before_it_is_an_error(
    core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.ensure()
    target = paths.cache / "x.json"
    target.write_text('{"a"', encoding="utf-8")  # a writer is mid-write

    def finish_the_write(_seconds: float) -> None:
        target.write_text('{"a": 1}', encoding="utf-8")

    monkeypatch.setattr(core.time, "sleep", finish_the_write)
    assert core.read_json_object(target, "x") == {"a": 1}
    target.write_text("{still broken", encoding="utf-8")
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)
    with pytest.raises(core.BridgeError, match="not readable JSON"):
        core.read_json_object(target, "x")


# ---------------------------------------------------------------- router hardening
def _other_gateway() -> Any:
    from conftest import FakeGateway

    server = FakeGateway()
    server.thread.start()
    return server


def test_router_does_not_follow_redirects_or_leak_the_token(
    core: Any, paths: Any, gateway: Any, router_env: Any
) -> None:
    other = _other_gateway()
    try:
        gateway.state.redirect_to = other.url + "/v1/chat/completions"
        with pytest.raises(core.RouterError, match="307") as caught:
            core.resolve(paths, system="", prompt="p", mode="router", env=router_env)
        assert other.state.requests == []  # the redirect target never saw the token
        assert SECRET_TOKEN not in str(caught.value)
    finally:
        other.shutdown()
        other.server_close()


@pytest.mark.parametrize("url", ["http://example.com", "http://192.168.1.20:3300", "http://10.0.0.5"])
def test_plain_http_is_only_for_loopback_and_host_docker_internal(core: Any, url: str) -> None:
    env = {"JJ_BRIDGE_BASE_URL": url, "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": "t"}
    with pytest.raises(core.RouterError, match="plain http"):
        core.router_config(env)


@pytest.mark.parametrize("url", ["https://example.com", "http://localhost:3300",
                                 "http://127.0.0.1:20128", "http://host.docker.internal:3300"])
def test_allowed_router_urls(core: Any, url: str) -> None:
    env = {"JJ_BRIDGE_BASE_URL": url, "JJ_BRIDGE_MODEL": "m", "JJ_BRIDGE_TOKEN": "t"}
    assert core.router_config(env).base_url == url


def test_oversized_router_response_is_refused(
    core: Any, paths: Any, gateway: Any, router_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "MAX_RESPONSE_BYTES", 64)
    gateway.state.reply_text = "x" * 1000
    with pytest.raises(core.RouterError, match="exceeds"):
        core.resolve(paths, system="", prompt="p", mode="router", env=router_env)
    assert not list(paths.cache.glob("*.json"))


def test_router_ignores_proxy_environment(
    core: Any, paths: Any, gateway: Any, router_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # dead proxy: would break or capture the call
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    result = core.resolve(paths, system="", prompt="p", mode="router", env=router_env)
    assert result.answer == "gateway answer" and len(gateway.state.requests) == 1


# ---------------------------------------------------------------- Windows sharing violations / partial files
def test_replace_is_retried_when_a_reader_briefly_holds_the_file(
    core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.ensure()
    real = os.replace
    attempts: list[int] = []

    def flaky(src: Any, dst: Any) -> None:
        attempts.append(1)
        if len(attempts) < 4:
            raise PermissionError(5, "Access is denied (WinError 5)")
        real(src, dst)

    monkeypatch.setattr(core.os, "replace", flaky)
    core.write_heartbeat(paths, "t")
    assert len(attempts) == 4 and core.chat_is_live(paths)
    assert not list(paths.base.glob("*.tmp"))


def test_replace_gives_up_loudly_after_the_retry_budget(core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    paths.ensure()

    def denied(src: Any, dst: Any) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(core.os, "replace", denied)
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        core.write_heartbeat(paths, "t")
    assert not list(paths.base.glob("*.tmp"))


def test_a_lost_heartbeat_read_does_not_flip_a_live_chat_to_dead(
    core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    core.write_heartbeat(paths, "t")
    real = Path.read_text
    losses: list[int] = []

    def flaky(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == "heartbeat.json" and len(losses) < 3:
            losses.append(1)
            raise PermissionError(13, "sharing violation")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert core.chat_is_live(paths) is True and len(losses) == 3


def test_a_heartbeat_that_stays_unreadable_is_eventually_not_live(
    core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    core.write_heartbeat(paths, "t")

    def always(self: Path, *args: Any, **kwargs: Any) -> str:
        raise PermissionError(13, "locked")

    monkeypatch.setattr(Path, "read_text", always)
    assert core.heartbeat_age(paths) is None


def test_the_no_hardlink_fallback_deletes_its_partial_final_file_on_failure(
    core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.ensure()
    target = paths.entry(paths.outbox, "e" * 64)
    real = core._write_synced
    calls: list[Path] = []

    def no_link(*args: Any, **kwargs: Any) -> None:
        raise OSError(errno.EPERM, "hard links unsupported")

    def die_on_the_final_file(path: Path, payload: bytes, exclusive: bool = False) -> None:
        calls.append(path)
        if path == target:
            real(path, payload[: len(payload) // 2], exclusive)
            raise OSError(errno.ENOSPC, "disk full")
        real(path, payload, exclusive)

    monkeypatch.setattr(core.os, "link", no_link)
    monkeypatch.setattr(core, "_write_synced", die_on_the_final_file)
    with pytest.raises(OSError):
        core.atomic_create_json(target, {"v": 1})
    assert not target.exists() and not list(paths.outbox.glob("*"))
    assert target in calls


def test_the_fallback_never_deletes_a_file_somebody_else_created(
    core: Any, paths: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.ensure()
    target = paths.entry(paths.outbox, "f" * 64)
    target.write_text('{"owner": "someone else"}', encoding="utf-8")

    def no_link(*args: Any, **kwargs: Any) -> None:
        raise OSError(errno.EPERM, "hard links unsupported")

    monkeypatch.setattr(core.os, "link", no_link)
    assert core.atomic_create_json(target, {"v": 1}) is False
    assert json.loads(target.read_text("utf-8")) == {"owner": "someone else"}


# ---------------------------------------------------------------- total router deadline
def test_a_trickling_gateway_is_cut_off_at_the_total_deadline(
    core: Any, paths: Any, gateway: Any, router_env: Any
) -> None:
    import time

    gateway.state.trickle_s = 0.15  # every read succeeds quickly: only a TOTAL deadline can stop it
    started = time.monotonic()
    with pytest.raises(core.RouterError, match="total deadline") as caught:
        core.resolve(paths, system="", prompt="p", mode="router", env=router_env, timeout_s=1)
    assert time.monotonic() - started < 4
    assert SECRET_TOKEN not in str(caught.value)
    assert not list(paths.cache.glob("*.json"))

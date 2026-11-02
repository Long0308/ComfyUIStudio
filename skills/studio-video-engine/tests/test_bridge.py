"""``jjv bridge serve`` (host bridge for a ComfyUI graph node): FAKE Codex CLI, fake ComfyUI input dir, real HTTP on 127.0.0.1.

No network beyond loopback, no real Codex, no GPU, no real machine.json.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from engine.bridge import images_job, secret as secret_mod, server as server_mod, video_job
from engine.bridge.config import BridgeConfig
from engine.core.errors import Refused
from images_fixtures import World, make_png, python_cmd, sha


def sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

FAKE = Path(__file__).with_name("fake_codex.py")
NEWT = "newtecons_live_action"
TEXT = "A site engineer checks a rebar cage at dusk, wide shot, documentary photo."


class Bridge:
    def __init__(self, tmp: Path, allowed=("acct3",), slow: float = 0.0) -> None:
        self.world = World(tmp, domain=NEWT)
        self.homes = {}
        for label in ("acct1", "acct3", "acct4"):
            home = tmp / "homes" / label
            home.mkdir(parents=True)
            (home / "auth.json").write_text("SECRET-DO-NOT-READ", encoding="utf-8")
            self.homes[label] = home
        self.world.machine["images"] = {
            "codex_accounts": [{"label": k, "codex_home": str(v)} for k, v in self.homes.items()],
            "codex_state_path": str(tmp / "pool-state.json"), "batch_ref_roots": [str(tmp)]}
        self.world.write_machine()
        self.png = make_png(tmp / "fake-image.png", (10, 20, 30), (320, 180))
        env = {**os.environ, "FAKE_CODEX_PNG": str(self.png), "FAKE_CODEX_SLEEP": str(slow)}
        self.state = tmp / "bridge-state"
        self.cfg = BridgeConfig(state_dir=self.state, accounts=tuple(allowed), machine_path=self.world.machine_path,
                                codex_cmd=python_cmd(FAKE), timeout=30.0, base_env=env)
        self.server = server_mod.make_server(self.cfg, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.secret = secret_mod.load_or_create(self.cfg.secret_path)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def call(self, method: str, path: str, body=None, secret: str | None = "default"):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.url + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if secret is not None:
            request.add_header("Authorization", "Bearer " + (self.secret if secret == "default" else secret))
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def wait(self, job_id: str, seconds: float = 30.0) -> dict:
        deadline = time.time() + seconds
        while time.time() < deadline:
            _, doc = self.call("GET", f"/v1/jobs/{job_id}")
            if doc.get("state") in ("done", "partial", "failed"):
                return doc
            time.sleep(0.1)
        raise AssertionError(f"job {job_id} did not finish: {doc}")

    def image_body(self, **kw) -> dict:
        body = {"episode": str(self.world.root), "prompt_text": TEXT, "n": 2, "kind": "SHOT", "client_id": "ui-7"}
        body.update(kw)
        return body


@pytest.fixture()
def bridge(tmp_path):
    made = Bridge(tmp_path)
    yield made
    made.server.shutdown()
    made.server.server_close()


# ---------------------------------------------------------------- secret
def test_secret_is_created_once_and_its_folder_is_gitignored(tmp_path):
    path = tmp_path / "state" / "secret"
    first = secret_mod.load_or_create(path)
    assert len(first) >= 32 and secret_mod.load_or_create(path) == first
    assert (path.parent / ".gitignore").read_text("utf-8").strip() == "*"
    assert secret_mod.authorized({"Authorization": f"Bearer {first}"}, first)
    assert not secret_mod.authorized({"Authorization": "Bearer nope"}, first)
    assert not secret_mod.authorized({}, first)


def test_every_job_endpoint_requires_the_secret(bridge):
    for secret in (None, "wrong-secret"):
        code, doc = bridge.call("POST", "/v1/images/codex", bridge.image_body(), secret=secret)
        assert code == 401 and doc["ok"] is False
        code, _ = bridge.call("GET", "/v1/jobs/whatever", secret=secret)
        assert code == 401
    assert not (bridge.state / "jobs").exists() or not any((bridge.state / "jobs").iterdir())
    code, doc = bridge.call("GET", "/v1/health", secret=None)
    assert code == 200 and doc["ok"] is True and "secret" not in json.dumps(doc).lower().replace("secret_required", "")


# ---------------------------------------------------------------- images
@pytest.mark.parametrize("n", [11, 0, -1, True, "10", 2.5])
def test_bad_n_is_refused_before_any_job_exists(bridge, n):
    code, doc = bridge.call("POST", "/v1/images/codex", bridge.image_body(n=n))
    assert code == 400 and doc["ok"] is False and "n" in doc["error"]
    assert not (bridge.state / "jobs").exists() or not any((bridge.state / "jobs").iterdir())


def test_validate_defaults_n_to_ten_and_rejects_empty_prompt():
    assert images_job.validate_request({"episode": "e", "prompt_text": "x"})["n"] == 10
    with pytest.raises(Refused, match="prompt_text"):
        images_job.validate_request({"episode": "e", "prompt_text": "  "})
    with pytest.raises(Refused, match="kind"):
        images_job.validate_request({"episode": "e", "prompt_text": "x", "kind": "PORTRAIT"})


def test_codex_job_writes_provenance_and_lands_images_in_the_comfy_input_dir(bridge):
    code, started = bridge.call("POST", "/v1/images/codex", bridge.image_body(prompt_id="BR_TEST_1"))
    assert code == 202 and started["state"] in ("queued", "running")
    doc = bridge.wait(started["job_id"])
    assert doc["state"] == "done" and len(doc["images"]) == 2, doc
    input_dir = bridge.world.comfy_root / "input"
    for image in doc["images"]:
        landed = input_dir / image["input_relpath"]
        assert landed.is_file() and sha(landed) == image["sha256"]
        assert image["input_relpath"].startswith(f"codex-lane/{started['job_id']}/")
        receipt = json.loads(Path(image["receipt"]).read_text("utf-8"))
        assert receipt["output"]["sha256"] == image["sha256"] and receipt["prompt_id"] == "BR_TEST_1"
        assert image["account_label"] == "acct3"
    job_dir = bridge.state / "jobs" / started["job_id"]
    queue = json.loads(next((job_dir / "prompt").glob("queue-*.json")).read_text("utf-8"))[0]
    assert queue["dispatch_allowed"] is True and queue["domain"] == NEWT and queue["source"] == "prompt_route"
    record = json.loads(next((job_dir / "prompt" / "confirmations").glob("BR_TEST_1-*.json")).read_text("utf-8"))
    assert record["by"] == "comfyui-run:ui-7"
    assert not (bridge.homes["acct1"] / "calls.jsonl").exists()  # a label outside the allow-list is never used
    assert "SECRET-DO-NOT-READ" not in json.dumps(doc)


def test_image_refs_from_the_graph_are_saved_and_sent(bridge, tmp_path):
    import base64

    ref = make_png(tmp_path / "ref.png", (200, 10, 10), (64, 64))
    body = bridge.image_body(n=1, refs=[{"role": "identity", "png_base64": base64.b64encode(ref.read_bytes()).decode()}])
    code, started = bridge.call("POST", "/v1/images/codex", body)
    assert code == 202
    doc = bridge.wait(started["job_id"])
    assert doc["state"] == "done", doc
    call = json.loads((bridge.homes["acct3"] / "calls.jsonl").read_text("utf-8").splitlines()[0])
    sent = call["argv"][call["argv"].index("-i") + 1]
    assert Path(sent).is_file() and sha(Path(sent)) == sha(ref)


def test_a_failed_lane_reports_failed_with_the_reason(bridge):
    (bridge.homes["acct3"] / "quota.flag").write_text("You've hit your usage limit. Try again in 2 hours.", "utf-8")
    code, started = bridge.call("POST", "/v1/images/codex", bridge.image_body(n=1))
    assert code == 202
    doc = bridge.wait(started["job_id"])
    assert doc["state"] == "failed" and doc["images"] == [] and doc["errors"], doc


def test_allow_list_is_required_and_bound_to_machine_labels(tmp_path):
    with pytest.raises(Refused, match="allow-list"):
        BridgeConfig(state_dir=tmp_path / "s", accounts=())
    world = Bridge(tmp_path / "w", allowed=("acct9",))
    try:
        with pytest.raises(Refused, match="acct9"):
            images_job.allowed_accounts(world.cfg, world.world.ctx())
    finally:
        world.server.shutdown()
        world.server.server_close()


def test_wildcard_bind_addresses_are_refused(tmp_path):
    cfg = BridgeConfig(state_dir=tmp_path / "s", accounts=("acct3",))
    for host in ("0.0.0.0", "::", ""):
        with pytest.raises(Refused, match="loopback"):
            server_mod.make_server(cfg, host, 0)


# ---------------------------------------------------------------- video
SLEEPER = [sys.executable, "-c", "import json,sys,time; time.sleep(3); print(json.dumps({'ok': True, 'argv': sys.argv[1:]}))"]


def test_video_endpoint_returns_at_once_and_the_job_finishes_detached(tmp_path):
    made = Bridge(tmp_path)
    made.cfg.jjv_cmd = SLEEPER
    try:
        started_at = time.time()
        code, started = made.call("POST", "/v1/video/shot", {"episode": str(made.world.root), "out": str(tmp_path / "v"),
                                                             "verb": "run", "dry_run": True, "shot": "S01_A"})
        assert code == 202 and time.time() - started_at < 2.0 and started["state"] == "running", started
        code, busy = made.call("POST", "/v1/video/shot", {"episode": str(made.world.root), "out": str(tmp_path / "v")})
        assert code == 409 and "running" in busy["error"]
        doc = made.wait(started["job_id"], seconds=20)
        assert doc["state"] == "done" and doc["exit_code"] == 0, doc
        assert doc["result"]["argv"][:3] == ["video", "run", "--episode"] and "--dry-run" in doc["result"]["argv"]
    finally:
        made.server.shutdown()
        made.server.server_close()


def test_video_argv_never_invents_a_gpu_approval_and_render_needs_its_fields():
    req = video_job.validate_request({"episode": "e", "out": "o", "verb": "run"})
    assert "--gpu-approved" not in video_job.video_argv(req)
    req = video_job.validate_request({"episode": "e", "out": "o", "verb": "render", "shot": "S1", "revision": 2,
                                      "route": "h3-ref2va", "gpu_approved": "token:user ok"})
    argv = video_job.video_argv(req)
    assert argv[:2] == ["video", "render"] and argv[argv.index("--gpu-approved") + 1] == "token:user ok"
    with pytest.raises(Refused, match="revision"):
        video_job.validate_request({"episode": "e", "out": "o", "verb": "render", "shot": "S1", "route": "r"})
    with pytest.raises(Refused, match="verb"):
        video_job.validate_request({"episode": "e", "out": "o", "verb": "accept"})


# ---------------------------------------------------------------- CR-BRIDGE hardening
def test_only_loopback_hosts_may_bind(tmp_path):
    cfg = BridgeConfig(state_dir=tmp_path / "s", accounts=("acct3",))
    for host in ("192.168.1.10", "10.0.0.5", "example.com", "127.0.0.2", "0.0.0.0"):
        with pytest.raises(Refused, match="loopback"):
            server_mod.make_server(cfg, host, 0)
    assert not (tmp_path / "s").exists()  # refused before any state is created
    for host in ("127.0.0.1", "::1", "localhost"):
        assert server_mod.check_loopback_host(host)


def test_accounts_override_can_only_narrow_the_config_allow_list(tmp_path):
    from engine.bridge.config import resolve_accounts

    state = tmp_path / "s"
    state.mkdir()
    (state / "config.json").write_text(json.dumps({"accounts": ["acct3", "acct4"]}), encoding="utf-8")
    assert resolve_accounts(state, None) == ["acct3", "acct4"]
    assert resolve_accounts(state, "acct4") == ["acct4"]
    assert resolve_accounts(state, "acct3,acct5") == ["acct3"]  # acct5 is silently NOT added
    with pytest.raises(Refused, match="allow-list"):
        resolve_accounts(state, "acct5")
    assert resolve_accounts(tmp_path / "none", "acct3") == ["acct3"]  # no config.json: the flag is the list


@pytest.mark.parametrize("label", ["acct1", "acct2"])
def test_user_forbidden_labels_never_enter_an_allow_list(tmp_path, label):
    with pytest.raises(Refused, match="forbidden"):
        BridgeConfig(state_dir=tmp_path / "s", accounts=("acct3", label))


def test_video_episode_and_out_are_confined_to_the_workspace(tmp_path):
    root = tmp_path / "production-local"
    (root / "ep").mkdir(parents=True)
    base = {"episode": str(root / "ep"), "out": str(root / "ep" / "v"), "verb": "run"}
    assert video_job.validate_request(base, root=root)["out"] == (root / "ep" / "v").resolve().as_posix()
    assert video_job.validate_request({**base, "episode": "my-slug", "out": "rel/v"}, root=root)["out"].startswith(
        root.resolve().as_posix())
    for bad in ("../../outside", str(tmp_path / "outside"), "a/../../b", str(root / ".." / "x")):
        with pytest.raises(Refused, match="workspace"):
            video_job.validate_request({**base, "out": bad}, root=root)
        with pytest.raises(Refused, match="workspace"):
            video_job.validate_request({**base, "episode": bad}, root=root)


def test_jobs_folders_are_private_where_the_os_allows(tmp_path):
    from engine.bridge.jobs import JobStore, secure_dir

    store = JobStore(tmp_path / "jobs")
    job_id = store.new("cx", {"state": "queued"})
    folder = store.folder(job_id)
    assert folder.is_dir()
    applied = secure_dir(folder)
    if os.name == "nt":
        assert applied is False  # POSIX modes do nothing on NTFS; ACL limitation is documented in SKILL.md
    else:
        assert applied is True and (folder.stat().st_mode & 0o077) == 0
        assert (tmp_path / "jobs").stat().st_mode & 0o077 == 0


# ---------------------------------------------------------------- N prompts
def prompts_of(n: int) -> list[str]:
    return [f"{TEXT} Variation number {i}." for i in range(1, n + 1)]


def test_validate_accepts_one_to_ten_prompts_and_keeps_order():
    req = images_job.validate_request({"episode": "e", "prompts": prompts_of(10)})
    assert req["prompts"] == prompts_of(10) and req["n"] == 10 and req["prompt_text"] is None
    one = images_job.validate_request({"episode": "e", "prompts": ["x"], "n": 7})  # n is ignored when prompts is given
    assert one["n"] == 1


@pytest.mark.parametrize("bad", [[], prompts_of(11), ["ok", "  "], ["ok", 3], "not a list", [""], ["x" * (images_job.MAX_PROMPT_CHARS + 1)]])
def test_bad_prompts_are_refused(bad):
    with pytest.raises(Refused, match="prompts"):
        images_job.validate_request({"episode": "e", "prompts": bad})


def test_prompt_and_prompts_together_are_refused_and_prompt_n_still_works():
    with pytest.raises(Refused, match="prompts"):
        images_job.validate_request({"episode": "e", "prompts": ["a"], "prompt_text": "b"})
    assert images_job.validate_request({"episode": "e", "prompt_text": "x", "n": 3})["n"] == 3


def test_ten_prompts_get_own_provenance_and_land_in_prompt_order(tmp_path):
    made = Bridge(tmp_path, allowed=("acct3",))
    try:
        texts = prompts_of(4)
        code, started = made.call("POST", "/v1/images/codex", {"episode": str(made.world.root), "prompts": texts,
                                                              "kind": "SHOT", "client_id": "ui-9", "prompt_id": "BR_MP"})
        assert code == 202 and started["n"] == 4, started
        doc = made.wait(started["job_id"], seconds=60)
        assert doc["state"] == "done", doc
        assert [i["index"] for i in doc["items"]] == [1, 2, 3, 4]
        job_dir = made.state / "jobs" / started["job_id"]
        for item, text in zip(doc["items"], texts):
            assert item["prompt_sha256"] == sha256_text(text) and item["status"] == "done" and item["lane"] == "acct3"
            assert item["output_sha256"] and Path(item["receipt"]).is_file()
            receipt = json.loads(Path(item["receipt"]).read_text("utf-8"))
            assert receipt["output"]["sha256"] == item["output_sha256"] and receipt["prompt_id"] == item["prompt_id"]
            queue = json.loads(next((job_dir / "prompt" / f"p{item['index']:02d}").glob("queue-*.json")).read_text("utf-8"))[0]
            assert queue["dispatch_allowed"] is True and queue["prompt_sha256"] == item["prompt_sha256"]
            assert next((job_dir / "prompt" / f"p{item['index']:02d}" / "confirmations").glob("*.json")).is_file()
        assert [i["index"] for i in doc["images"]] == [1, 2, 3, 4]
        assert [Path(i["input_relpath"]).name[:3] for i in doc["images"]] == ["01_", "02_", "03_", "04_"]
        assert len({i["prompt_id"] for i in doc["items"]}) == 4
    finally:
        made.server.shutdown()
        made.server.server_close()


def test_a_dead_lane_hands_its_prompts_to_the_healthy_lane(tmp_path):
    made = Bridge(tmp_path, allowed=("acct3", "acct4"))
    try:
        (made.homes["acct4"] / "quota.flag").write_text("You've hit your usage limit. Try again in 2 hours.", "utf-8")
        code, started = made.call("POST", "/v1/images/codex", {"episode": str(made.world.root), "prompts": prompts_of(3)})
        assert code == 202
        doc = made.wait(started["job_id"], seconds=60)
        assert doc["state"] == "done" and [i["lane"] for i in doc["items"]] == ["acct3"] * 3, doc
        assert any(e.get("lane") == "acct4" for e in doc["errors"])
    finally:
        made.server.shutdown()
        made.server.server_close()


def test_all_lanes_dead_reports_every_prompt_failed(bridge):
    (bridge.homes["acct3"] / "quota.flag").write_text("You've hit your usage limit. Try again in 2 hours.", "utf-8")
    code, started = bridge.call("POST", "/v1/images/codex", {"episode": str(bridge.world.root), "prompts": prompts_of(2)})
    doc = bridge.wait(started["job_id"])
    assert doc["state"] == "failed" and [i["status"] for i in doc["items"]] == ["failed", "failed"] and doc["errors"]

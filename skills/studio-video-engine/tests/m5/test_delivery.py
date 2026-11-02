"""Tiny real ffmpeg clips plus a local fake Studio; no production writes."""
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from engine.core.errors import Refused, Uncertain
from engine.core.io import sha256_file
from engine.deliver.brand import join, seam_luma, title
from engine.deliver.cli import register_cli
from engine.deliver.common import audio_md5, load_context, probe
from engine.deliver.film import film_2k
from engine.publish.studio import local_url, publish_studio


def write(file, data):
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def context(tmp_path):
    episode = tmp_path / "episode" / "engine" / "episode.json"
    ep = {"episode_id": "test-episode", "film_id": "test-episode", "title": "A new title", "domain": "test-domain"}
    domain = {"domain_id": "test-domain", "delivery": {
        "master": {"width": 3840, "height": 2160, "fps": 30},
        "film_2k": {"width": 2560, "height": 1440, "method": "lanczos"}}}
    cfg = {"schema": "jjv/delivery-config/v1", "episode_id": ep["episode_id"], "domain": ep["domain"]}
    write(episode, ep)
    write(tmp_path / "skill" / "domains" / "test-domain.json", domain)
    write(tmp_path / "delivery.json", cfg)
    return load_context(episode, delivery_config=tmp_path / "delivery.json", repo_root=tmp_path,
                        skill_root=tmp_path / "skill")


def clip(file, *, frames=16, size="160x90", white=False):
    source = f"color=white:size={size}:rate=30" if white else f"testsrc=size={size}:rate=30"
    subprocess.run(["ffmpeg", "-n", "-v", "error", "-f", "lavfi", "-i", source,
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(frames / 30),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-threads", "2",
                    "-pix_fmt", "yuv420p", "-video_track_timescale", "90000", "-color_range", "tv",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(file)], check=True)
    return file


# Default kit: the ep04 brand kit beside this repository; absent on other machines -> skip.
DEFAULT_BRAND_KIT = Path(__file__).resolve().parents[5] / "production-local" / "JennieJoyKids-Story" / "_brand" / "intro-v001"


def kit_arg(request):
    explicit = request.config.getoption("--brand-kit")
    if explicit:
        return str(Path(explicit).resolve())  # an explicit path is used as given (missing -> test error)
    if not DEFAULT_BRAND_KIT.is_dir():
        pytest.skip("brand kit not on this machine (--brand-kit)")
    return str(DEFAULT_BRAND_KIT.resolve())


def test_film_2k_frame_and_audio_copy(context, tmp_path):
    master = clip(tmp_path / "master.mp4", frames=4, size="3840x2160")
    result = film_2k(context, master, tmp_path / "2k")
    assert result["output"]["frames"] == 4
    assert all(result["checks"].values())
    assert audio_md5(master, []) == audio_md5(tmp_path / "2k" / "film-2k.mp4", [])
    assert (tmp_path / "2k" / "receipt.json").is_file()
    with pytest.raises(Refused, match="already exists"):
        film_2k(context, master, tmp_path / "2k")


def test_refuse_review_as_master(context, tmp_path):
    review = clip(tmp_path / "review.mp4")
    with pytest.raises(Refused, match="declared master"):
        film_2k(context, review, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_lossless_join_and_framemd5(context, tmp_path, request):
    files = [clip(tmp_path / f"{name}.mp4") for name in ("intro", "title", "film")]
    context["config"]["brand"] = {"kit": kit_arg(request)}
    result = join(context, tmp_path / "joined", intro=str(files[0]), title_file=str(files[1]), film=str(files[2]))
    assert all(result["checks"].values())
    assert result["frame_proof"]["actual"] == 48
    assert len(result["frame_proof"]["files"]) == 4
    assert probe(tmp_path / "joined" / "branded-film.mp4", [])["frames"] == 48


def test_join_white_seam_is_rejected(context, tmp_path, request):
    intro = clip(tmp_path / "intro.mp4")
    title_file = clip(tmp_path / "title.mp4", white=True)
    film = clip(tmp_path / "film.mp4")
    context["config"]["brand"] = {"kit": kit_arg(request)}
    with pytest.raises(Refused, match="verification failed"):
        join(context, tmp_path / "joined", intro=str(intro), title_file=str(title_file), film=str(film))
    receipt = json.loads((tmp_path / "joined" / "receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["seam_luma"]["pure_white_frames"]


@pytest.fixture
def publication(context, tmp_path):
    artifact = tmp_path / "artifact.mp4"
    artifact.write_bytes(b"synthetic published artifact")
    digest = sha256_file(artifact)
    write(tmp_path / "media-receipt.json", {"output": {"path": str(artifact), "sha256": digest}})
    original = {"meta": {"keep": 1}, "films": [{"id": "other", "artifacts": [{"id": "old", "keep": True}]},
                {"id": "test-episode", "title": "Existing title", "custom": 9, "artifacts": []}]}
    # The film library is a write target: under the repo's production-local root (M8b-g5 containment).
    library = tmp_path / "production-local" / "film-library.json"
    write(library, original)
    cfg = {"library": str(library), "studio_url": "http://127.0.0.1:1", "artifacts": [{
        "path": str(artifact), "sha256": digest, "receipt": str(tmp_path / "media-receipt.json"),
        "role": "film_2k", "version": "v1", "provenance": "test fixture", "review_status": "CANDIDATE"}]}
    context["config"]["publish"] = cfg
    return context, original


@pytest.fixture
def fake_studio(publication):
    ctx, original = publication
    library = Path(ctx["config"]["publish"]["library"])
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            data = json.loads(library.read_text())
            for film in data["films"]:
                for row in film["artifacts"]:
                    row["exists"] = Path(row.get("path", "nonexistent")).is_file()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    ctx["config"]["publish"]["studio_url"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield ctx, original, calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_publish_dry_run_no_write_no_http(publication, tmp_path):
    ctx, _ = publication
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    result = publish_studio(ctx, out=tmp_path / "unused")
    assert result["new_count"] == 1
    assert result["dry_run"] is True
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_publish_additive_backup_readback_idempotent(fake_studio, tmp_path):
    ctx, original, calls = fake_studio
    result = publish_studio(ctx, publish=True, out=tmp_path / "publish")
    assert result["status"] == "verified" and result["readback"]["verified"]
    after = json.loads(Path(ctx["config"]["publish"]["library"]).read_text())
    assert after["films"][0] == original["films"][0]
    after["films"][1]["artifacts"] = []
    assert after == original
    assert json.loads((tmp_path / "publish" / "film-library.backup.json").read_text()) == original
    assert len(calls) == 1 and calls[0].startswith("/api/films?episode_id=")
    assert publish_studio(ctx)["new_count"] == 0
    before = Path(ctx["config"]["publish"]["library"]).read_bytes()
    assert publish_studio(ctx, publish=True, out=tmp_path / "again")["new_count"] == 0
    assert before == Path(ctx["config"]["publish"]["library"]).read_bytes()


def test_publish_existing_rows_never_overwritten(publication):
    ctx, _ = publication
    libfile = Path(ctx["config"]["publish"]["library"])
    library = json.loads(libfile.read_text())
    item = ctx["config"]["publish"]["artifacts"][0]
    library["films"][1]["artifacts"].append({"id": item["sha256"][:20], "sha256": "different"})
    write(libfile, library)
    before = libfile.read_bytes()
    with pytest.raises(Refused, match="collision"):
        publish_studio(ctx)
    assert libfile.read_bytes() == before


def test_publish_failure_receipt_retains_written_rows(publication, tmp_path, monkeypatch):
    ctx, _ = publication
    def fail(url):
        raise OSError("fake readback unavailable")
    monkeypatch.setattr("engine.publish.studio.get_json", fail)
    with pytest.raises(Uncertain, match="library was written"):
        publish_studio(ctx, publish=True, out=tmp_path / "failed")
    report = json.loads((tmp_path / "failed" / "receipt.json").read_text())
    assert report["library_written"] and report["status"] == "uncertain"
    assert publish_studio(ctx)["new_count"] == 0


@pytest.mark.parametrize("url", ["https://127.0.0.1", "http://example.com", "http://127.0.0.1@other", "http://127.0.0.1/x"])
def test_publish_refuses_external_urls(url):
    with pytest.raises(Refused):
        local_url(url, "test")


def test_publish_hash_binding_required(publication):
    ctx, _ = publication
    ctx["config"]["publish"]["artifacts"][0]["sha256"] = "f" * 64
    with pytest.raises(Refused, match="hash"):
        publish_studio(ctx)


def test_title_refuses_implicit_other_episode_defaults(context, tmp_path):
    context["config"]["brand"] = {"props": {"titleEn": "Another episode"}}
    with pytest.raises(Refused, match="explicitly"):
        title(context, tmp_path / "title")
    assert not (tmp_path / "title").exists()


def test_title_wraps_real_audio_and_mux(context, tmp_path, request, monkeypatch):
    from engine.deliver import brand
    real_run = brand.run
    picture = clip(tmp_path / "source.mp4")
    cfg = {"kit": kit_arg(request), "workspace": str(tmp_path), "packages": str(tmp_path / "packages"),
           "browser": str(tmp_path / "chrome"), "props": {"titleEn": "A new title", "titleVi": "Title VI",
           "subtitle": "New subtitle", "brandLine": "TEST", "background": "new.png", "logo": "logo.png"}}
    context["config"]["brand"] = cfg
    context["domain"]["delivery"]["master"] = {"width": 160, "height": 90}
    def mock_picture_renderer(argv, commands, **kwargs):
        if str(argv[0]) == "node":
            job = json.loads(Path(argv[2]).read_text())
            assert job["props"] == cfg["props"] and job["browser"] == cfg["browser"]
            real_run(["ffmpeg", "-n", "-v", "error", "-i", picture, "-an", "-c:v", "copy", job["out"]], commands)
            write(Path(job["out"] + ".render-record.json"), {"test_fixture": True})
            return ""
        return real_run(argv, commands, **kwargs)
    monkeypatch.setattr(brand, "run", mock_picture_renderer)
    result = title(context, tmp_path / "title")
    assert result["status"] == "verified"
    assert probe(tmp_path / "title" / "title.mp4", [])["audio_streams"] == 1


def test_cli_flags_and_stage_registration():
    import argparse
    parser = argparse.ArgumentParser()
    register_cli(parser.add_subparsers(dest="stage", required=True))
    for stage, verb in (("deliver", "film-2k"), ("brand", "title"), ("brand", "join"), ("publish", "studio")):
        argv = [stage, verb, "--episode", "example"]
        if stage == "deliver":
            argv += ["--master", "master.mp4"]
        args = parser.parse_args(argv)
        assert (args.stage, args.verb) == (stage, verb)
    with pytest.raises(SystemExit):
        parser.parse_args(["publish", "studio", "--episode", "example", "--publish", "--dry-run"])


def test_publish_preserves_existing_artifact_rows(fake_studio, tmp_path):
    ctx, _, _ = fake_studio
    libfile = Path(ctx["config"]["publish"]["library"])
    library = json.loads(libfile.read_text())
    old = {"id": "prior-row", "path": "keep-exactly", "sha256": "prior-sha", "custom": [1, 2]}
    library["films"][1]["artifacts"] = [old]
    write(libfile, library)
    publish_studio(ctx, publish=True, out=tmp_path / "publish")
    assert json.loads(libfile.read_text())["films"][1]["artifacts"][0] == old


def test_publish_wrong_readback_is_uncertain(publication, tmp_path, monkeypatch):
    ctx, _ = publication
    def wrong(url):
        return {"films": [{"id": "test-episode", "artifacts": []}]}
    monkeypatch.setattr("engine.publish.studio.get_json", wrong)
    with pytest.raises(Uncertain, match="library was written"):
        publish_studio(ctx, publish=True, out=tmp_path / "wrong")
    assert (tmp_path / "wrong" / "publication-intent.json").is_file()
    assert (tmp_path / "wrong" / "library-written.json").is_file()


def test_publish_refuses_existing_metadata_drift(fake_studio, tmp_path):
    ctx, _, _ = fake_studio
    publish_studio(ctx, publish=True, out=tmp_path / "first")
    libfile = Path(ctx["config"]["publish"]["library"])
    before = libfile.read_bytes()
    ctx["config"]["publish"]["artifacts"][0]["review_status"] = "APPROVED"
    with pytest.raises(Refused, match="collision"):
        publish_studio(ctx)
    assert libfile.read_bytes() == before

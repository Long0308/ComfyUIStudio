"""Generalise the legacy publishers' backup/additive-write/readback transaction.

An HTTP failure after replacement is persisted as uncertain; reruns never undo a write.
All writers using this adapter share an OS lock and compare the source bytes before replacement.
"""
from __future__ import annotations

import copy
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..core.errors import Refused, Uncertain
from ..core.filelock import run_lock
from ..core.io import read_json, sha256_file, write_atomic, write_once, write_json_once
from ..deliver.common import block, fresh, need, path, receipt, record, write_path


def local_url(base, film_id):
    url = urllib.parse.urlsplit(base)
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.username or url.password
            or url.query or url.fragment or url.path not in ("", "/")):
        raise Refused("Studio URL must be http://127.0.0.1[:port] without credentials/path")
    return base.rstrip("/") + "/api/films?" + urllib.parse.urlencode({"episode_id": film_id})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused("Studio readback redirect refused")


def get_json(url):
    # Do not honour proxy environment settings for local reads, or follow an external redirect.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=30) as response:
        return json.load(response)


def _bound_hash(value, digest):
    if isinstance(value, dict):
        return any((k in ("sha256", "output_sha256") and v == digest) or _bound_hash(v, digest)
                   for k, v in value.items())
    return isinstance(value, list) and any(_bound_hash(v, digest) for v in value)


def _field(item, key):
    if not isinstance(item, dict) or key not in item:
        raise Refused(f"publish artifact requires {key}")
    return item[key]


def rows_for(ctx):
    rows = []
    artifacts = need(block(ctx, "publish"), "artifacts", "publish")
    if not isinstance(artifacts, list):
        raise Refused("publish.artifacts must be a list")
    for item in artifacts:
        file = path(ctx, _field(item, "path"))
        evidence = path(ctx, item["binding_receipt"] if "binding_receipt" in item else _field(item, "receipt"))
        if not file.is_file() or not evidence.is_file():
            raise Refused(f"publish artifact or its receipt is missing: {file}")
        digest = sha256_file(file)
        if item.get("sha256") != digest:
            raise Refused(f"artifact hash does not match config: {file}")
        if not _bound_hash(read_json(evidence), digest):
            raise Refused(f"receipt does not bind artifact sha256: {file}")
        row = {"id": digest[:20], "path": str(file), "sha256": digest, "job_id": None,
               "filename": file.name, "receipt": str(path(ctx, _field(item, "receipt")))}
        for key in ("role", "version", "provenance", "review_status"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise Refused(f"publish artifact requires explicit {key}")
            row[key] = item[key]
        rows.append(row)
    ids = [row["id"] for row in rows]
    if not rows or len(set(ids)) != len(ids):
        raise Refused("publish artifacts must be non-empty with unique content ids")
    return rows


def _plan(library, film_id, rows):
    films = [f for f in library["films"] if f["id"] == film_id]
    if len(films) > 1:
        raise Refused("duplicate film ids in library")
    film = films[0] if films else None
    have = {}
    for f in library["films"]:
        for row in f.get("artifacts", []):
            if f["id"] == film_id:
                if row["id"] in have:
                    raise Refused("duplicate artifact ids in library")
                have[row["id"]] = row
    for row in rows:
        old = have.get(row["id"])
        if old and any(old.get(k) != value for k, value in row.items()):
            raise Refused(f"existing artifact id collision: {row['id']}; no rows changed")
    return film, [r for r in rows if r["id"] not in have], [r["id"] for r in rows if r["id"] in have]


def _readback(data, film_id, rows):
    films = [f for f in data["films"] if f["id"] == film_id]
    if len(films) != 1:
        raise Uncertain("readback did not contain exactly one requested film")
    artifacts = films[0]["artifacts"]
    checks = {}
    for row in rows:
        matches = [a for a in artifacts if a["id"] == row["id"]]
        checks[row["id"]] = (len(matches) == 1 and matches[0].get("exists") is True
                              and all(matches[0].get(k) == value for k, value in row.items()))
    return {"checks": checks, "verified": all(checks.values())}


def publish_studio(ctx, *, publish=False, out=None):
    cfg = block(ctx, "publish")
    # The film library is a WRITE target: it must sit under the machine's production-local root, never through a link.
    library_path = write_path(ctx, need(cfg, "library", "publish"), Path(ctx["repo_root"]) / "production-local",
                              "publish.film_library")
    film_id = ctx["episode"].get("film_id", ctx["episode"]["episode_id"])
    url = local_url(need(cfg, "studio_url", "publish"), film_id)
    rows = rows_for(ctx)
    if not library_path.is_file():
        raise Refused(f"publish library not found: {library_path}")
    original = library_path.read_bytes()
    library = json.loads(original.decode("utf-8-sig"))
    _, new, already = _plan(library, film_id, rows)
    summary = {"schema": "jjv/publish-studio/v1", "film_id": film_id,
               "dry_run": not publish, "new_rows": new, "new_count": len(new), "already": already}
    if not publish:
        return summary  # no mkdir, backup, receipt, lock or HTTP on dry run
    if out is None:
        raise Refused("publication requires a fresh receipt output directory")
    out = fresh(out)
    result = {**summary, "binding": ctx["binding"], "status": "prepared", "readback_url": url,
              "library": str(library_path), "library_before": record(library_path)}
    wrote = False
    try:
        with run_lock(library_path.with_name(library_path.name + ".publish.lock"), timeout_seconds=0):
            rows = rows_for(ctx)  # source bytes/evidence may have changed while waiting for the lock
            original = library_path.read_bytes()
            library = json.loads(original.decode("utf-8-sig"))
            film, new, already = _plan(library, film_id, rows)
            result.update(new_rows=new, new_count=len(new), already=already,
                          library_before=record(library_path))
            backup = out / "film-library.backup.json"
            write_once(backup, original)
            result["backup"] = record(backup)
            write_json_once(out / "publication-intent.json", result, mode="utf8", stamp=True)
            if new:
                updated = copy.deepcopy(library)
                if film is None:
                    updated["films"].append({"id": film_id, "title": ctx["episode"]["title"], "artifacts": new})
                else:
                    next(f for f in updated["films"] if f["id"] == film_id).setdefault("artifacts", []).extend(new)
                if library_path.read_bytes() != original:
                    raise Refused("library changed outside the publication lock; retry from a fresh plan")
                write_atomic(library_path, (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                wrote = True
            result["library_after"] = record(library_path)
            write_json_once(out / "library-written.json", {"library_written": wrote,
                            "library_after": result["library_after"], "rows": rows}, mode="utf8", stamp=True)
            result["readback"] = _readback(get_json(url), film_id, rows)
            if not result["readback"]["verified"]:
                raise Uncertain("Studio readback does not match published rows")
            result["status"] = "verified"
    except Exception as exc:
        result.update(status="uncertain" if wrote else "failed", error=str(exc), library_written=wrote)
        if wrote:
            raise Uncertain(f"library was written; reconcile receipt before retrying: {exc}") from exc
        raise
    finally:
        receipt(out, result)
    return result

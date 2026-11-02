"""Host-side assets for the NEWTECONS step UI ComfyUI extension (newtecons_step_ui).

refs            copy (never move) the chosen internal reference images into
                ComfyUI input/reference-library/{face,pose}/ so LoadImage can read
                them as 'reference-library/face/<file>'. Identical existing copy = skip;
                a different file at the target = refuse.
engine-library  make small JPEG thumbnails of the CURRENT engine images listed in
                library-r005f-by-character/INDEX.json (all produced by the Codex OAuth
                lane, `jjv images ... --provider codex-exec`) into
                input/engine-library-r005f/, plus a manifest JSON the extension reads.
                Source PNGs are only read; their sha256 is checked against INDEX.json.

No network, no GPU, no ComfyUI calls. Never deletes or overwrites a file.
Usage:
  python -I step_ui_assets.py refs
  python -I step_ui_assets.py engine-library
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[5]
INPUT_DIR = REPO / 'production-local' / 'ComfyUI' / 'input'
REF_LIB = REPO / 'production-local' / 'reference-library' / 'by-type'
ENGINE_LIB = (REPO / 'production-local' / 'JennieJoyKids-Story' / 'Newtecons-TienDo-KichTinh-30s'
              / 'production-v2-45s' / 'library-r005f-by-character')
EXT_WEB = REPO / 'production-local' / 'ComfyUI' / 'custom_nodes' / 'newtecons_step_ui' / 'web'
MANIFEST_NAME = 'engine_library_r005f.json'
THUMB_SUBDIR = 'engine-library-r005f'
THUMB_MAX = 512

# Chosen by eye on 2026-10-31 (contact sheets): neutral grey-background closeups and a
# standing neutral manikin. full_sexy poses deliberately excluded for corporate NEWTECONS.
REFERENCES = (
    ('face', REF_LIB / 'face' / 'closeup' / 'f01d89535c5.webp'),
    ('face', REF_LIB / 'face' / 'closeup' / 'f02920397d9.webp'),
    ('pose', REF_LIB / 'pose' / 'full_single' / 'full' / 'full_single_P017_front.png'),
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def copy_exclusive(src: Path, dst: Path) -> str:
    """Copy src to dst without overwriting. Returns 'copied' or 'identical'."""
    want = sha256_file(src)
    if dst.exists():
        if sha256_file(dst) != want:
            raise ValueError('target exists with different content: %s' % dst)
        return 'identical'
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open('rb') as fin, dst.open('xb') as fout:
        shutil.copyfileobj(fin, fout)
    if sha256_file(dst) != want:
        raise ValueError('copy verification failed: %s' % dst)
    return 'copied'


def toplevel_name(kind: str, src: Path) -> str:
    return 'newtecons_ref_%s_%s' % (kind, src.name)


def copy_references(input_dir: Path, references=REFERENCES) -> list[dict]:
    """Two copies per reference: input/reference-library/<kind>/<file> (the internal library
    layout) and a top-level input/newtecons_ref_<kind>_<file>. Measured 2026-10-31 (frontend
    1.55.17): LoadImage's combo lists only top-level files, and a subfolder value — although the
    server accepts it (VALIDATE_INPUTS) — is marked has_errors (red node) by the frontend. The
    workflow therefore uses the top-level copy."""
    rows = []
    for kind, src in references:
        lib = input_dir / 'reference-library' / kind / src.name
        top = input_dir / toplevel_name(kind, src)
        states = (copy_exclusive(src, lib), copy_exclusive(src, top))
        rows.append({'kind': kind, 'source': str(src), 'library_copy': str(lib), 'toplevel_copy': str(top),
                     'loadimage_value': top.name, 'sha256': sha256_file(top), 'state': list(states)})
    return rows


def thumbnail_bytes(src: Path, max_side: int = THUMB_MAX) -> bytes:
    from PIL import Image  # local import: only this subcommand needs Pillow
    with Image.open(src) as im:
        im = im.convert('RGB')
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=85, optimize=True)
    return buf.getvalue()


def _receipt_fields(path: str) -> dict:
    try:
        r = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'receipt_error': '%s: %s' % (type(exc).__name__, exc)}
    return {'provider': r.get('provider'), 'route': r.get('route'), 'domain': r.get('domain'),
            'receipt_status': r.get('status'), 'resolved_model': r.get('resolved_model')}


def build_engine_library(library: Path, input_dir: Path) -> dict:
    index = json.loads((library / 'INDEX.json').read_text(encoding='utf-8'))
    items = []
    for char, kinds in sorted(index['characters'].items()):
        for kind, entries in sorted(kinds.items()):
            for it in entries:
                src = library / it['file']
                src_sha = sha256_file(src)
                data = thumbnail_bytes(src)
                sub = '%s/%s/%s' % (THUMB_SUBDIR, char, kind)
                dst = input_dir / sub / (src.stem + '.jpg')
                if dst.exists():
                    if dst.read_bytes() != data:
                        raise ValueError('thumbnail exists with different content: %s' % dst)
                    state = 'identical'
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    with dst.open('xb') as stream:
                        stream.write(data)
                    state = 'written'
                items.append({'char': char, 'kind': kind, 'label': src.stem.split('__')[0],
                              'subfolder': sub, 'filename': dst.name,
                              'thumb_sha256': hashlib.sha256(data).hexdigest(), 'thumb_state': state,
                              'source_file': str(src), 'source_sha256': src_sha,
                              'source_sha256_matches_index': src_sha == it.get('sha256'),
                              'rev': it.get('rev'), 'prompt_id': it.get('prompt_id'),
                              **_receipt_fields(it.get('receipt', ''))})
    return {'schema': 'newtecons.step_ui.engine_library.v1',
            'status': 'CANDIDATE_NOT_APPROVED — thumbnails for comparison only, not wardrobe canon',
            'route_note': 'Generated by the Codex OAuth lane outside ComfyUI (jjv images ... --provider codex-exec).',
            'library': str(library), 'index_sha256': sha256_file(library / 'INDEX.json'),
            'current_revs': index.get('current_revs'), 'thumb_max_side': THUMB_MAX,
            'count': len(items),
            'sha_mismatches': sum(1 for i in items if not i['source_sha256_matches_index']),
            'providers': sorted({str(i.get('provider')) for i in items}),
            'items': items}


def write_json_new_or_same(path: Path, payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=1) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') == text:
            return 'identical'
        raise ValueError('refusing to overwrite %s (move it to an archive first)' % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    return 'written'


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('command', choices=('refs', 'engine-library'))
    p.add_argument('--input-dir', type=Path, default=INPUT_DIR)
    p.add_argument('--library', type=Path, default=ENGINE_LIB)
    p.add_argument('--manifest', type=Path, default=EXT_WEB / MANIFEST_NAME)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if a.command == 'refs':
            rows = copy_references(a.input_dir)
            print(json.dumps({'references': rows}, ensure_ascii=False, indent=1))
            return 0
        payload = build_engine_library(a.library, a.input_dir)
        state = write_json_new_or_same(a.manifest, payload)
        print(json.dumps({'manifest': str(a.manifest), 'state': state, 'count': payload['count'],
                          'sha_mismatches': payload['sha_mismatches'], 'providers': payload['providers'],
                          'manifest_sha256': sha256_file(a.manifest)}, ensure_ascii=False))
        return 0 if payload['sha_mismatches'] == 0 else 1
    except (OSError, ValueError, KeyError) as exc:
        print('REFUSED: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

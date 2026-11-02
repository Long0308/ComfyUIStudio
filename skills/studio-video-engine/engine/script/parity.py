"""Read-only reference comparison: report differences, never reconcile the script by hand."""
from __future__ import annotations

from pathlib import Path

from ..core.io import read_json


def differences(actual, reference, path: str = '$') -> list[dict]:
    if isinstance(actual, dict) and isinstance(reference, dict):
        return [row for key in sorted(actual.keys() | reference.keys())
                for row in differences(actual.get(key), reference.get(key), f'{path}.{key}')]
    if isinstance(actual, list) and isinstance(reference, list):
        return [row for i in range(max(len(actual), len(reference)))
                for row in differences(actual[i] if i < len(actual) else None,
                                       reference[i] if i < len(reference) else None, f'{path}[{i}]')]
    return [] if actual == reference else [{'path': path, 'generated': actual, 'reference': reference}]


def compare(derived: Path, *, shots: Path, boundaries: Path, delivery_contract: Path) -> dict:
    generated_shots = read_json(derived / 'shots.json')['shots']
    reference_shots = read_json(shots)['shots']
    generated_bounds = read_json(derived / 'boundaries-input.json')['boundaries']
    reference_bounds = read_json(boundaries)['boundaries']
    generated_contract = read_json(derived / 'DELIVERY-CONTRACT.json')
    reference_contract = read_json(delivery_contract)
    actual = {'shot_ids': [s['shot'] for s in generated_shots], 'boundary_count': len(generated_bounds),
              'total_frames': generated_contract['master']['frames'],
              'sections': generated_contract['sections'],
              'boundaries': [{k: b[k] for k in ('from_shot', 'to_shot', 'frame')} for b in generated_bounds]}
    reference = {'shot_ids': [s['shot'] for s in reference_shots], 'boundary_count': len(reference_bounds),
                 'total_frames': reference_contract['master']['frames'], 'sections': reference_contract['sections'],
                 'boundaries': [{k: b[k] for k in ('from_shot', 'to_shot', 'frame')} for b in reference_bounds]}
    delta = differences(actual, reference)
    return {'schema': 'jjv/script-parity/v1', 'equal': not delta, 'generated': actual, 'reference': reference,
            'differences': delta,
            'explanation': 'Authoring schedule is preserved; reference may include later H3 splits, measured WAVs and approved holds. No historical media binding is invented.'}

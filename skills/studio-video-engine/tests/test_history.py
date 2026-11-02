from __future__ import annotations

import copy

import pytest

from engine.comfy.history import history_entries, select_bound_entry
from engine.core.errors import Failed, Uncertain

GRAPH = {"1": {"class_type": "LoadVideo", "inputs": {"file": "a.mp4", "n": 1}}}
CLIENT = "client-A"


def entry(
    prompt_id: str = "p1",
    graph: dict | None = None,
    client: str = CLIENT,
    status: dict | None = None,
) -> dict:
    return {
        "prompt": [7, prompt_id, copy.deepcopy(GRAPH if graph is None else graph),
                   {"client_id": client}, ["15"]],
        "outputs": {},
        "status": status or {"status_str": "success", "completed": True, "messages": []},
    }


def test_selects_single_bound_entry_from_comfy_shape() -> None:
    history = {"p1": entry("p1"), "p2": entry("p2", client="other")}
    assert select_bound_entry(history, prompt_id="p1", graph=GRAPH, client_id=CLIENT)["prompt"][1] == "p1"


def test_finds_entries_wherever_nested() -> None:
    assert len(history_entries({"wrap": [{"x": entry("p1")}], "junk": 3})) == 1
    assert history_entries({"prompt": [1, 2]}) == []


def test_no_match_is_uncertain_not_resubmit() -> None:
    with pytest.raises(Uncertain):
        select_bound_entry({}, prompt_id="p1", graph=GRAPH, client_id=CLIENT)
    with pytest.raises(Uncertain):
        select_bound_entry({"p": entry(client="other")}, prompt_id="p1", graph=GRAPH, client_id=CLIENT)


def test_graph_must_match_exactly() -> None:
    other = copy.deepcopy(GRAPH)
    other["1"]["inputs"]["file"] = "b.mp4"
    with pytest.raises(Uncertain):
        select_bound_entry({"p": entry(graph=other)}, prompt_id="p1", graph=GRAPH, client_id=CLIENT)


def test_true_and_one_are_not_conflated() -> None:
    boolean = {"1": {"class_type": "X", "inputs": {"flag": True}}}
    numeric = {"1": {"class_type": "X", "inputs": {"flag": 1}}}
    assert True == 1  # the hazard plain == would have
    with pytest.raises(Uncertain):
        select_bound_entry({"p": entry(graph=numeric)}, prompt_id="p1", graph=boolean, client_id=CLIENT)


def test_duplicate_prompt_id_is_uncertain() -> None:
    history = [{"a": entry("p1")}, {"b": entry("p1")}]
    with pytest.raises(Uncertain):
        select_bound_entry(history, prompt_id="p1", graph=GRAPH, client_id=CLIENT)


def test_prompt_id_is_a_required_keyword() -> None:
    with pytest.raises(TypeError):
        select_bound_entry({"p": entry()}, graph=GRAPH, client_id=CLIENT)  # type: ignore[call-arg]


def test_unknown_prompt_id_is_uncertain() -> None:
    history = {"p1": entry("p1"), "p2": entry("p2")}
    with pytest.raises(Uncertain):
        select_bound_entry(history, prompt_id="p3", graph=GRAPH, client_id=CLIENT)
    got = select_bound_entry(history, prompt_id="p2", graph=GRAPH, client_id=CLIENT)
    assert got["prompt"][1] == "p2"


def test_other_prompt_with_our_graph_is_never_returned() -> None:
    """Regression (critic T-E15c): history {P: graph H, Q: graph G}; we POSTed P
    with graph G.  Q carries our graph but is not our prompt: must NOT return Q."""
    other_graph = {"1": {"class_type": "Other", "inputs": {}}}
    history = {"P": entry("P", graph=other_graph), "Q": entry("Q", graph=GRAPH)}
    with pytest.raises(Uncertain):
        select_bound_entry(history, prompt_id="P", graph=GRAPH, client_id=CLIENT)
    assert select_bound_entry(history, prompt_id="Q", graph=GRAPH, client_id=CLIENT)["prompt"][1] == "Q"


def test_prompt_found_but_client_differs_is_uncertain() -> None:
    with pytest.raises(Uncertain):
        select_bound_entry({"P": entry("P", client="x")}, prompt_id="P", graph=GRAPH, client_id=CLIENT)


@pytest.mark.parametrize(
    "status",
    [{"status_str": "error", "completed": False},
     {"status_str": "success", "completed": False},
     {"status_str": "success"}],
)
def test_unsuccessful_or_incomplete_is_failed(status: dict) -> None:
    with pytest.raises(Failed):
        select_bound_entry({"p": entry(status=status)}, prompt_id="p1", graph=GRAPH, client_id=CLIENT)


def test_missing_status_is_uncertain() -> None:
    broken = entry()
    del broken["status"]
    with pytest.raises(Uncertain):
        select_bound_entry({"p": broken}, prompt_id="p1", graph=GRAPH, client_id=CLIENT)


# ComfyUI 0.41 records some integer widget values as floats in /history (measured on
# the ep04 tails run 2026-10-27: SaveVideo "format.codec.encoding.crf" 16 -> 16.0).
# The v004 executor compared dicts with ==, so it never tripped on this; the engine
# compares canonical bytes and must treat an integral float as the same number.
def test_comfy_integral_float_matches_submitted_int() -> None:
    submitted = {"15": {"class_type": "SaveVideo", "inputs": {"format.codec.encoding.crf": 16}}}
    recorded = {"15": {"class_type": "SaveVideo", "inputs": {"format.codec.encoding.crf": 16.0}}}
    hit = select_bound_entry({"p": entry(graph=recorded)}, prompt_id="p1", graph=submitted, client_id=CLIENT)
    assert hit["prompt"][1] == "p1"


def test_comfy_integral_float_matches_submitted_sha() -> None:
    from engine.core.io import canonical_sha256
    submitted = {"15": {"class_type": "SaveVideo", "inputs": {"crf": 16}}}
    recorded = {"15": {"class_type": "SaveVideo", "inputs": {"crf": 16.0}}}
    sha = canonical_sha256(submitted, mode="ascii")
    hit = select_bound_entry({"p": entry(graph=recorded)}, prompt_id="p1", graph_sha256=sha, client_id=CLIENT)
    assert hit["prompt"][1] == "p1"


def test_non_integral_float_is_still_a_different_graph() -> None:
    submitted = {"1": {"class_type": "X", "inputs": {"v": 16}}}
    recorded = {"1": {"class_type": "X", "inputs": {"v": 16.5}}}
    with pytest.raises(Uncertain):
        select_bound_entry({"p": entry(graph=recorded)}, prompt_id="p1", graph=submitted, client_id=CLIENT)


def test_true_and_one_float_are_not_conflated() -> None:
    boolean = {"1": {"class_type": "X", "inputs": {"flag": True}}}
    numeric = {"1": {"class_type": "X", "inputs": {"flag": 1.0}}}
    with pytest.raises(Uncertain):
        select_bound_entry({"p": entry(graph=numeric)}, prompt_id="p1", graph=boolean, client_id=CLIENT)


def test_prompt_records_match_a_submitted_sha_despite_float_widgets() -> None:
    from engine.comfy.queue import prompt_records
    from engine.core.io import canonical_sha256
    submitted = {"15": {"class_type": "SaveVideo", "inputs": {"crf": 16}}}
    recorded = {"15": {"class_type": "SaveVideo", "inputs": {"crf": 16.0}}}
    sha = canonical_sha256(submitted, mode="ascii")
    records = prompt_records({"p": entry(graph=recorded)}, "history")
    assert len(records) == 1 and records[0].matches(sha)
    assert not records[0].matches(canonical_sha256({"15": {"class_type": "SaveVideo", "inputs": {"crf": 17}}},
                                                   mode="ascii"))


def test_verify_known_prompt_accepts_float_widgets_from_comfy() -> None:
    from engine.comfy.reconcile import verify_known_prompt
    from engine.core.io import canonical_sha256
    submitted = {"15": {"class_type": "SaveVideo", "inputs": {"crf": 16}}}
    recorded = {"15": {"class_type": "SaveVideo", "inputs": {"crf": 16.0}}}

    class Client:
        def get(self, path: str) -> dict:
            return {"p1": entry("p1", graph=recorded)} if path.startswith("/history/") else \
                {"queue_running": [], "queue_pending": []}

    records = verify_known_prompt(Client(), prompt_id="p1", graph_sha256=canonical_sha256(submitted, mode="ascii"),
                                  client_id=CLIENT)
    assert [r.prompt_id for r in records] == ["p1"]


# Shape measured on the real ep04 tails history (S03_B chunk-0000, ComfyUI 0.41): the submitted
# graph carries int crf 16 AND floats cfg/denoise 1.0; ComfyUI records crf as 16.0. Neither the
# raw submitted sha nor a one-sided normalisation matches; identity against identity does.
REAL_SUBMITTED = {"10": {"class_type": "SeedVR2", "inputs": {"cfg": 1.0, "denoise": 1.0, "seed": 42}},
                  "15": {"class_type": "SaveVideo", "inputs": {"format.codec.encoding.crf": 16}}}
REAL_RECORDED = {"10": {"class_type": "SeedVR2", "inputs": {"cfg": 1.0, "denoise": 1.0, "seed": 42}},
                 "15": {"class_type": "SaveVideo", "inputs": {"format.codec.encoding.crf": 16.0}}}


def test_mixed_float_graph_matches_by_identity_on_both_sides() -> None:
    from engine.comfy.graph_identity import wanted_shas
    from engine.comfy.queue import prompt_records
    from engine.core.io import canonical_sha256
    raw = canonical_sha256(REAL_SUBMITTED, mode="ascii")
    history = {"p1": entry("p1", graph=REAL_RECORDED)}
    record = prompt_records(history, "history")[0]
    assert not record.matches(raw)  # the bare receipt sha alone can not name it (the bug)
    assert record.matches(wanted_shas(REAL_SUBMITTED, raw))
    hit = select_bound_entry(history, prompt_id="p1", client_id=CLIENT, graph_sha256=wanted_shas(REAL_SUBMITTED, raw))
    assert hit["prompt"][1] == "p1"
    assert select_bound_entry(history, prompt_id="p1", client_id=CLIENT, graph=REAL_SUBMITTED)["prompt"][1] == "p1"


def test_mixed_float_graph_resume_verify_known_prompt() -> None:
    from engine.comfy.graph_identity import wanted_shas
    from engine.comfy.reconcile import reconcile_intent, verify_known_prompt
    from engine.core.io import canonical_sha256
    raw = canonical_sha256(REAL_SUBMITTED, mode="ascii")

    class Client:
        def get(self, path: str) -> dict:
            if path.startswith("/history"):
                return {"p1": entry("p1", graph=REAL_RECORDED)}
            return {"queue_running": [], "queue_pending": []}

    wanted = wanted_shas(REAL_SUBMITTED, raw)
    assert [r.prompt_id for r in verify_known_prompt(Client(), prompt_id="p1", graph_sha256=wanted,
                                                     client_id=CLIENT)] == ["p1"]
    assert reconcile_intent(Client(), graph_sha256=wanted, client_id=CLIENT).prompt_id == "p1"
    other = dict(REAL_SUBMITTED, **{"15": {"class_type": "SaveVideo", "inputs": {"format.codec.encoding.crf": 17}}})
    with pytest.raises(Uncertain):
        verify_known_prompt(Client(), prompt_id="p1", graph_sha256=wanted_shas(other), client_id=CLIENT)

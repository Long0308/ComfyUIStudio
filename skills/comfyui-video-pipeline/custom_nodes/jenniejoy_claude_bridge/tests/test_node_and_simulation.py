from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
import simulate_end_to_end

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")


class FakeTensor:
    """Quacks like a torch IMAGE tensor: ``.cpu().numpy()``."""

    def __init__(self, array: Any) -> None:
        self._array = array

    def cpu(self) -> "FakeTensor":
        return self

    def numpy(self) -> Any:
        return self._array


def _image(value: float = 0.5, shape: tuple[int, ...] = (1, 4, 6, 3)) -> FakeTensor:
    return FakeTensor(np.full(shape, value, dtype=np.float32))


@pytest.fixture
def node(pack: Any, shared: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("JJ_BRIDGE_SHARED", str(shared))
    for name in ("JJ_BRIDGE_BASE_URL", "JJ_BRIDGE_MODEL", "JJ_BRIDGE_TOKEN", "JJ_BRIDGE_API"):
        monkeypatch.delenv(name, raising=False)
    return pack.NODE_CLASS_MAPPINGS["JJClaudeBridge"]()


def test_node_contract(pack: Any, core: Any) -> None:
    cls = pack.NODE_CLASS_MAPPINGS["JJClaudeBridge"]
    assert cls.CATEGORY == "JennieJoy/Authoring"
    assert cls.RETURN_TYPES == ("STRING", "STRING")
    assert cls.RETURN_NAMES == ("answer", "receipt")
    assert cls.FUNCTION == "run" and hasattr(cls, "run")
    spec = cls.INPUT_TYPES()
    required = spec["required"]
    assert required["prompt"][0] == "STRING" and required["prompt"][1]["multiline"] is True
    assert required["system"][0] == "STRING"
    assert required["mode"][0] == ["auto", "cache_only", "chat", "router"]
    assert required["timeout_s"][0] == "INT" and required["timeout_s"][1]["default"] == 600
    assert spec["optional"] == {"image": ("IMAGE",)}
    assert list(pack.NODE_CLASS_MAPPINGS) == ["JJClaudeBridge"]
    assert not hasattr(cls, "OUTPUT_NODE") or cls.OUTPUT_NODE is not True


def test_is_changed_is_the_cache_key(pack: Any, core: Any) -> None:
    cls = pack.NODE_CLASS_MAPPINGS["JJClaudeBridge"]
    assert cls.IS_CHANGED("p", "s", "auto", 600) == core.cache_key("s", "p", [])
    assert cls.IS_CHANGED("p", "s", "chat", 5) == cls.IS_CHANGED("p", "s", "auto", 600)
    with_image = cls.IS_CHANGED("p", "s", "auto", 600, _image())
    assert with_image != cls.IS_CHANGED("p", "s", "auto", 600)
    assert with_image == cls.IS_CHANGED("p", "s", "auto", 600, _image())
    assert with_image != cls.IS_CHANGED("p", "s", "auto", 600, _image(0.25))


def test_image_hash_is_over_pixels_and_png_is_valid(pack: Any) -> None:
    from PIL import Image
    import io

    blobs = pack.node.tensor_to_images(_image(0.5))
    assert len(blobs) == 1
    pixels = np.clip(255.0 * np.full((4, 6, 3), 0.5, dtype=np.float32), 0, 255).astype(np.uint8)
    expected = hashlib.sha256(b"(4, 6, 3):" + pixels.tobytes()).hexdigest()
    assert blobs[0].sha256 == expected
    decoded = Image.open(io.BytesIO(blobs[0].png))
    assert decoded.size == (6, 4) and decoded.format == "PNG"
    assert pack.node.tensor_to_images(None) == []
    batch = pack.node.tensor_to_images(_image(0.1, (3, 2, 2, 3)))
    assert len(batch) == 3 and len({b.sha256 for b in batch}) == 1


def test_bad_image_shape_is_refused(pack: Any, core: Any) -> None:
    with pytest.raises(core.BridgeError, match="IMAGE must be"):
        pack.node.tensor_to_images(FakeTensor(np.zeros((4, 4), dtype=np.float32)))


def test_run_returns_strings_via_router_then_replays(
    pack: Any, core: Any, node: Any, gateway: Any, router_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in router_env.items():
        monkeypatch.setenv(name, value)
    first = node.run("hello", "sys", "router", 30)
    assert isinstance(first[0], str) and isinstance(first[1], str)
    assert first[0] == "gateway answer" and json.loads(first[1])["route"] == "router"
    gateway.state.reply_text = "changed"
    second = node.run("hello", "sys", "auto", 30)
    assert second == first and len(gateway.state.requests) == 1


def test_run_with_image_stores_it_in_the_shared_folder(
    pack: Any, core: Any, node: Any, shared: Any, gateway: Any, router_env: Any,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in router_env.items():
        monkeypatch.setenv(name, value)
    node.run("what is this", "", "router", 30, _image())
    blob = pack.node.tensor_to_images(_image())[0]
    saved = shared / "claude-bridge" / "images" / f"{blob.sha256}.png"
    assert saved.read_bytes() == blob.png


def test_run_auto_without_a_route_raises(core: Any, node: Any) -> None:
    with pytest.raises(core.NoRouteAvailable):
        node.run("nothing configured", "", "auto", 5)


def test_default_shared_folder_follows_the_comfyui_layout(pack: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JJ_BRIDGE_SHARED", raising=False)
    derived = pack.node._paths().base
    assert derived.name == "claude-bridge" and derived.parent.name == "user"


def test_end_to_end_simulation_with_the_real_mcp_server() -> None:
    result = simulate_end_to_end.run_simulation(log=lambda _line: None)
    assert result["answer"] == "A lone crane lifts steel into the dawn."
    assert result["receipt"]["route"] == "chat"

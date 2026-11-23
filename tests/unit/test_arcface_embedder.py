"""ArcFace embedder: landmark alignment, ONNX run, and the FACE_EMBEDDER switch."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
onnx = pytest.importorskip("onnx")

from core.recognition import embedder as E  # noqa: E402


def _tiny_model(path):
    from onnx import TensorProto, helper, numpy_helper
    w = numpy_helper.from_array(np.random.default_rng(0).standard_normal((3 * 112 * 112, 512)).astype(np.float32), "w")
    shape = numpy_helper.from_array(np.array([1, -1], dtype=np.int64), "shape")
    g = helper.make_graph(
        [helper.make_node("Reshape", ["x", "shape"], ["f"]), helper.make_node("MatMul", ["f", "w"], ["y"])],
        "tiny", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 112, 112])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 512])], [w, shape])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
    m.ir_version = 8
    onnx.save(m, str(path))


def _row(scale=2.0, dx=30.0, dy=20.0):
    pts = E.ARCFACE_TEMPLATE * scale + [dx, dy]
    return np.array([0, 0, 1, 1, *pts.ravel(), 0.99], dtype=np.float32)


def test_align_maps_landmarks_to_template():
    img = np.zeros((400, 400, 3), np.uint8)
    row = _row()
    for x, y in row[4:14].reshape(5, 2):
        cv2.circle(img, (int(round(x)), int(round(y))), 3, (255, 255, 255), -1)
    out = E.align_112(img, row)
    assert out.shape == (112, 112, 3)
    for x, y in E.ARCFACE_TEMPLATE:
        assert out[int(round(y)), int(round(x))].max() > 100


def test_arcface_embeds_unit_vector(tmp_path):
    p = tmp_path / "arc.onnx"
    _tiny_model(p)
    emb = E.ArcFaceEmbedder(p)
    assert emb.available() and emb.name == "arcface-arc"
    img = np.random.default_rng(1).integers(0, 255, (300, 300, 3), dtype=np.uint8)
    v = emb.embed(img, _row())
    assert v.shape == (512,) and abs(np.linalg.norm(v) - 1) < 1e-4
    assert E.similarity(v, emb.embed(img, _row())) > 0.999


def test_choose_falls_back_to_sface_when_model_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("FACE_EMBEDDER", "arcface")
    monkeypatch.setattr(E, "ARCFACE_MODEL", tmp_path / "missing.onnx")
    monkeypatch.setattr(E.ArcFaceEmbedder.__init__, "__defaults__", (tmp_path / "missing.onnx",))
    assert isinstance(E.choose(), E.SFaceEmbedder)


def test_choose_uses_arcface_when_present(monkeypatch, tmp_path):
    p = tmp_path / "arc.onnx"
    _tiny_model(p)
    monkeypatch.setenv("FACE_EMBEDDER", "arcface")
    monkeypatch.setattr(E.ArcFaceEmbedder.__init__, "__defaults__", (p,))
    assert isinstance(E.choose(), E.ArcFaceEmbedder)

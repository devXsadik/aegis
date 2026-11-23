"""Training metrics, and smoke runs proving the exported models fit what the runtime loads."""
import csv
import shutil

import cv2
import numpy as np
import pytest

from training.common import accuracy, confusion, per_class_accuracy, reid_rank1_map


def test_classification_metrics():
    cm = confusion([0, 0, 1, 1, 2], [0, 1, 1, 1, 0], 3)
    assert cm.tolist() == [[1, 1, 0], [0, 2, 0], [1, 0, 0]]
    assert accuracy(cm) == pytest.approx(0.6)
    assert per_class_accuracy(cm, ["a", "b", "c"]) == {"a": 0.5, "b": 1.0, "c": 0.0}


def test_reid_metrics():
    q = np.array([[1, 0], [0, 1]], float)
    g = np.array([[0.9, 0.1], [0.1, 0.9], [0.8, 0.3]], float)
    m = reid_rank1_map(q, ["a", "b"], g, ["a", "b", "a"])
    assert m["rank1"] == 1.0 and m["mAP"] == 1.0
    m = reid_rank1_map(q, ["a", "b"], g, ["b", "a", "a"])
    assert m["rank1"] == 0.0 and 0 < m["mAP"] < 1
    # same-camera matches do not count
    m = reid_rank1_map(q[:1], ["a"], g[:1], ["a"], ["c1"], ["c1"])
    assert m["queries"] == 0


def _attr_dataset(root, n=24):
    (root / "images" / "train").mkdir(parents=True)
    (root / "images" / "test").mkdir(parents=True)
    colors = {"white": (240, 240, 240), "red": (30, 30, 220)}
    rows = []
    for i in range(n):
        c = "white" if i % 2 else "red"
        img = np.full((40, 60, 3), colors[c], np.uint8)
        split = "test" if i >= n - 6 else "train"
        name = f"images/{split}/{i}.jpg"
        cv2.imwrite(str(root / name), img)
        rows.append([name, split, "day", "car" if i % 3 else "bus", c, ""])
    with open(root / "labels.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "split", "day_night", "vehicle_type", "color", "make_model"])
        w.writerows(rows)


def test_attribute_trainer_smoke_and_runtime_contract(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    from training import train_attributes
    data = tmp_path / "ds"
    _attr_dataset(data)
    res = train_attributes.main(["--data", str(data), "--out", str(tmp_path / "runs"), "--epochs", "8",
                                 "--backbone", "tiny", "--size", "32"])
    run = __import__("pathlib").Path(res["dir"])
    assert (run / "model.onnx").exists() and (run / "labels.json").exists()
    assert res["metrics"]["test"]["color"]["accuracy"] >= 0.5
    # the runtime (core/analysis/vehicle_attrs.py) loads the exported pair as-is
    from core.analysis import vehicle_attrs
    live = tmp_path / "live"
    live.mkdir()
    shutil.copy(run / "model.onnx", live / "vehicle_attr.onnx")
    shutil.copy(run / "labels.json", live / "vehicle_attr.labels.json")
    monkeypatch.setattr(vehicle_attrs, "MODELS", str(live))
    vehicle_attrs._net.cache_clear()
    vehicle_attrs._attr_labels.cache_clear()
    try:
        out = vehicle_attrs.classify(np.full((40, 60, 3), (240, 240, 240), np.uint8))
        assert out["model"].startswith("attr-") and out["color"] in ("white", "red") and "color" in out["confidences"]
    finally:
        vehicle_attrs._net.cache_clear()
        vehicle_attrs._attr_labels.cache_clear()


def test_reid_trainer_smoke(tmp_path):
    pytest.importorskip("torch")
    from training import train_reid
    root = tmp_path / "ds"
    for split, ids in (("train", range(4)), ("test", range(4, 6))):
        for ident in ids:
            d = root / "images" / split / f"v{ident}"
            d.mkdir(parents=True)
            for k in range(3):
                img = np.full((48, 48, 3), (ident * 40 % 255, 255 - ident * 30, (ident * 70) % 255), np.uint8)
                img[k * 5:k * 5 + 10, :] = 0
                cv2.imwrite(str(d / f"{k}.jpg"), img)
    res = train_reid.main(["--data", str(root), "--out", str(tmp_path / "runs"), "--epochs", "2", "--backbone", "tiny"])
    assert 0 <= res["metrics"]["rank1"] <= 1 and res["metrics"]["queries"] == 2
    net = cv2.dnn.readNetFromONNX(res["dir"] + "/model.onnx")
    net.setInput(np.zeros((1, 3, 256, 256), np.float32))
    v = net.forward().ravel()
    assert abs(np.linalg.norm(v) - 1) < 1e-3

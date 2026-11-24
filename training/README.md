# Training our own vehicle models

Three models, all trained on our cameras' data after pre-training on public sets:

| Task | Script | Public pre-training | Output the runtime loads | Metric |
|---|---|---|---|---|
| Weapon detector (BD deshi blades + firearms) | `train_detector.py` + `configs/weapon.yaml` | COCO YOLO; `datasets/weapons` (BD_Deshi_Weapon_Dataset_v1) | `models/weapon_yolo.pt` | mAP50, mAP50-95, per-class AP |
| Vehicle detector + BD classes (CNG, leguna, easy-bike…) | `train_detector.py` (Ultralytics YOLOv8 / YOLO11) | COCO weights; BD road datasets (e.g. "Dhaka-AI", "BadODD") where licences allow | `models/vehicle_detect.onnx` | mAP50, mAP50-95, per-class AP |
| Colour + type + make/model (one backbone, three heads) | `train_attributes.py` (EfficientNet-B0 / ConvNeXt-T) | ImageNet | `models/vehicle_attr.onnx` + `vehicle_attr.labels.json` | per-class accuracy, confusion matrix, day vs night |
| Vehicle re-identification | `train_reid.py` (ResNet-50 + BNNeck, CE + batch-hard triplet) | VeRi-776 (`--format veri`) | `models/vehicle_reid.onnx` | Rank-1, mAP |

## The loop

1. **Collect** — Dashboard → *Models & data*: create a dataset (task), upload images, or road scenes
   with *Crop vehicles* on (the COCO detector cuts out each vehicle). Operator corrections and rejected
   matches land in the **review queue**; add them to the next dataset version.
2. **Label** — set type / colour / make-model per item (lists come from Settings → Vehicle classes),
   boxes for detector sets, identity for re-ID. Or label in CVAT / Label Studio and import (YOLO / COCO).
3. **Split** — stratified by class (re-ID: by identity, no leakage), fixed seed. Check the
   **balance report** (per class, per split, day / night) before training.
4. **Freeze** — the version becomes read-only and records the class lists. Later changes → new version.
5. **Export** the dataset (`yolo`, `coco`, `attributes`, `reid` zip) and **train**:

```sh
python -m training.train_attributes --data attrs_v3_attributes.zip
python -m training.train_reid --data VeRi/ --format veri            # pre-train
python -m training.train_reid --data reid_v2_reid.zip --init runs/reid/<run>/model.pt
python -m training.train_detector --data det_v4_yolo.zip
```

### Weapons at CCTV distance

The labelled weapon photos are close-ups (weapon ~110 px); on a camera the same weapon is 15-40 px.
A model trained only on the photos finds ~1 % of weapons at that size. Three parts fix it:

1. **Synthetic data** — `training/synth_weapons.py` pastes the weapon cut-outs into camera frames, at
   a person's wrist, sized to the person, blurred and compressed like CCTV, plus weapon-free frames as
   hard negatives and the same frames as enlarged person crops. Splits never share a cut-out or a
   frame. Your own camera footage as `--backgrounds` matters most.
2. **3 classes** (blade / firearm / blunt) instead of 10 with 12-30 examples each; the alert does not
   use the type.
3. **Person crops at run time** — `weapon.mode: both` in `config/config.yaml` also looks at each
   person enlarged to 640 px (`core/detectors/weapon_detector.py`).

```sh
python -m training.synth_weapons --crops <BD_Deshi_Weapon_Dataset_v1>/classification_crops \
    --real datasets/weapons --backgrounds <your clips> datasets/_bg/coco128/images/train2017 \
    --classes 3 --out datasets/weapons_cctv
python -m training.train_detector --data datasets/weapons_cctv \
    --config training/configs/weapon_cctv.yaml --install models/weapon_yolo.pt
python -m training.evaluate_weapons models/weapon_yolo.pt --data datasets/weapons_cctv
```

Never validate on the training images (`datasets/weapons_all` does): the score is then memory.
`evaluate_weapons` reports, on held-out data only, the share of weapons found as photographed,
shrunk to CCTV size, and in synthetic camera frames with and without person crops, plus false alarms
on weapon-free frames. Synthetic frames are not real footage: before relying on weapon alerts,
record staged footage (props, your cameras, day and night) and check it with
`scripts/evaluate_accuracy.py`.

   Each run writes `runs/<task>/<time>/` with `config.json` (incl. git commit), `metrics.json`,
   `model.onnx` (and `labels.json`). Same data + config + seed → same split and comparable numbers.
6. **Register** — `python -m training.register runs/attributes/<time> --task vehicle_attr --version 1.3 --token …`
   (starts in *staging*).
7. **Promote** in the dashboard registry: the file is swapped atomically into `models/`, the previous
   production model is archived. **Rollback** restores the last one. Both are audit-logged.

GPU: train on a CUDA box (`TRAIN_MPS=1` allows Apple GPUs, slow for these sizes). TensorRT for
inference: `yolo export model=best.pt format=engine half=True`, or `trtexec --onnx=model.onnx --fp16`.

## Honest expectations

Accuracy depends on labelled BD footage: a few hundred examples per colour / type class and
thousands for make/model. Until then the baselines run (HSV colour vote, COCO types, histogram
re-ID) and matching weighs them low; plate-less "candidate" alerts stay limited to lookouts.
Watch the Accuracy dashboard (Analytics → Accuracy) after every promotion.

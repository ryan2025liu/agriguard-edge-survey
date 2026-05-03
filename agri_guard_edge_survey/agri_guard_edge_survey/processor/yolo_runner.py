"""
[INPUT]: A single YOLO model path, device id, and image slices.
[OUTPUT]: Detections as tuples (class_id, confidence, cx, cy, w, h) in slice pixel space.
[POS]: Performance boundary — one model load per survey run.
[PROTOCOL]:
 1. Match coordinate convention with `agri_guard_core.inference.run_inference` (xywh center).
 2. Pass device through to Ultralytics the same way as `agri_guard_edge_ai.detector.YoloDetector`.
"""

from __future__ import annotations

from typing import Any, List, Tuple

DetectionTuple = Tuple[int, float, float, float, float, float]


class CachedYoloRunner:
    def __init__(self, model_path: str, device: str):
        self._model_path = model_path
        self._device = device
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from ultralytics import YOLO  # type: ignore

            self._model = YOLO(self._model_path)
        return self._model

    def predict(self, image_slice: Any, confidence: float) -> List[DetectionTuple]:
        model = self._load()
        kwargs = {"verbose": False, "conf": confidence}
        if self._device:
            kwargs["device"] = self._device
        results = model(image_slice, **kwargs)
        out: List[DetectionTuple] = []
        for r in results:
            for box in r.boxes:
                x, y, w, h = box.xywh[0].tolist()
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                out.append((cls_id, conf, float(x), float(y), float(w), float(h)))
        return out

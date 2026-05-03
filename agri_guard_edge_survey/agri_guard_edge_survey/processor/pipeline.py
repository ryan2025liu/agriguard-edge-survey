"""
[INPUT]: Input directory, output directory, model path, tiling and clustering hyperparameters.
[OUTPUT]: `ProcessingResult` with counts and duration.
[POS]: Core batch pipeline for Edge Survey CLI (`survey process`).
[PROTOCOL]:
 1. Do not copy or upload original rasters.
 2. One `CachedYoloRunner` per run.
 3. If `results.db` exists, refuse unless `--force` (deletes local artifacts index — user must confirm data loss).
 4. **SIGINT**: first Ctrl+C requests cooperative stop (checked between images/tiles); second Ctrl+C calls `os._exit(130)` if still blocked inside native GPU work.
"""

from __future__ import annotations

import logging
import math
import os
import signal
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Dict, List, Optional

from agri_guard_core.clustering import cluster_detections
from agri_guard_core.geo import project_pixel_to_gps
from agri_guard_core.metadata import MetadataError, get_image_metadata
from agri_guard_core.pil_open import open_image
from agri_guard_core.tiling import slice_image
from tqdm import tqdm

from agri_guard_edge_survey.processor.yolo_runner import CachedYoloRunner
from agri_guard_edge_survey.storage.local_db import LocalDatabase
from agri_guard_edge_survey.storage.output_writer import OutputWriter

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".JPG", ".JPEG", ".dng", ".DNG")


@dataclass
class ProcessingResult:
    total_images: int
    processed_images: int
    failed_images: int
    detection_count: int
    incident_count: int
    duration_seconds: float
    output_dir: Path
    mission_id: int


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c


def _pick_best_evidence(
    inc_lat: float,
    inc_lon: float,
    class_id: int,
    flat: List[Dict[str, Any]],
    max_meters: float,
) -> Optional[str]:
    best_path: Optional[str] = None
    best_conf = -1.0
    for d in flat:
        if d.get("lat") is None or d.get("lon") is None:
            continue
        if d.get("class_id") != class_id:
            continue
        if _haversine_m(inc_lat, inc_lon, float(d["lat"]), float(d["lon"])) > max_meters:
            continue
        conf = float(d.get("confidence", 0))
        if conf > best_conf:
            best_conf = conf
            best_path = d.get("evidence_path")
    return best_path


class ProcessingPipeline:
    def __init__(
        self,
        *,
        input_dir: Path,
        output_dir: Path,
        model_path: Path,
        mission_name: Optional[str],
        confidence_threshold: float,
        tile_size: int,
        overlap: float,
        cluster_eps: float,
        generate_l2: bool,
        device: str,
        force: bool = False,
    ):
        self.input_dir = input_dir.resolve()
        self.output_dir = output_dir.resolve()
        self.model_path = model_path.resolve()
        self.mission_name = mission_name or self._default_mission_name()
        self.confidence_threshold = confidence_threshold
        self.tile_size = tile_size
        self.overlap = overlap
        self.cluster_eps = cluster_eps
        self.generate_l2 = generate_l2
        self.device = device
        self.force = force

        self.db_path = self.output_dir / "results.db"
        self.db = LocalDatabase(self.db_path)
        self.writer = OutputWriter(self.output_dir)
        self._yolo: Optional[CachedYoloRunner] = None
        self._interrupt: Optional[Dict[str, bool]] = None

    def _default_mission_name(self) -> str:
        from datetime import datetime

        return f"survey-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def _scan_images(self) -> List[Path]:
        found: List[Path] = []
        for ext in SUPPORTED_EXTENSIONS:
            found.extend(self.input_dir.rglob(f"*{ext}"))
        return sorted(set(found))

    def _ensure_output_ready(self) -> None:
        if self.force:
            for sub in ("evidence", "l2_previews", "logs"):
                p = self.output_dir / sub
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
            if self.db_path.exists():
                self.db_path.unlink()
            man = self.output_dir / "manifest.json"
            if man.exists():
                man.unlink()
            return

        if self.db_path.exists():
            raise FileExistsError(
                f"{self.db_path} already exists. Use --force to overwrite output directory state."
            )

    def _check_interrupt(self) -> None:
        flag = self._interrupt
        if flag and flag["stop"]:
            raise KeyboardInterrupt

    def run(self) -> ProcessingResult:
        start = time.perf_counter()
        interrupt: Dict[str, bool] = {"stop": False}

        def _on_sigint(_signum: int, _frame: FrameType | None) -> None:
            # First Ctrl+C: cooperative stop at next image/tile boundary.
            # Second: hard exit (GPU/CUDA may ignore Python until then).
            if interrupt["stop"]:
                os._exit(130)
            interrupt["stop"] = True

        prev_sigint = signal.signal(signal.SIGINT, _on_sigint)
        self._interrupt = interrupt
        try:
            return self._run_body(start)
        finally:
            signal.signal(signal.SIGINT, prev_sigint)
            self._interrupt = None

    def _run_body(self, start: float) -> ProcessingResult:
        self._ensure_output_ready()
        self.writer.ensure_layout()
        self.db.init_schema()

        image_paths = self._scan_images()
        total = len(image_paths)

        config: Dict[str, Any] = {
            "confidence_threshold": self.confidence_threshold,
            "tile_size": self.tile_size,
            "overlap": self.overlap,
            "cluster_eps_meters": self.cluster_eps,
            "device": self.device,
            "generate_l2": self.generate_l2,
            "input_dir": str(self.input_dir),
        }
        mission_id = self.db.create_mission(
            name=self.mission_name,
            total_images=total,
            model_path=str(self.model_path),
            config=config,
        )

        self._yolo = CachedYoloRunner(str(self.model_path), self.device)
        flat_detections: List[Dict[str, Any]] = []
        processed = 0
        failed = 0

        for img_path in tqdm(image_paths, desc="images", unit="img"):
            self._check_interrupt()
            try:
                n = self._process_one_image(
                    mission_id=mission_id,
                    img_path=img_path,
                    flat_detections=flat_detections,
                )
                processed += 1
                logger.debug("Processed %s detections=%d", img_path.name, n)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.error("Failed %s: %s", img_path, exc, exc_info=True)

        cluster_input: List[Dict[str, Any]] = [
            {
                "lat": d["lat"],
                "lon": d["lon"],
                "class_id": d["class_id"],
                "confidence": d["confidence"],
            }
            for d in flat_detections
            if d.get("lat") is not None and d.get("lon") is not None
        ]

        incident_count = 0
        if cluster_input:
            self.db.delete_incidents_for_mission(mission_id)
            clusters = cluster_detections(cluster_input, eps_meters=self.cluster_eps)
            pick_radius = max(self.cluster_eps * 4.0, 8.0)
            for c in clusters:
                best = _pick_best_evidence(
                    float(c["lat"]),
                    float(c["lon"]),
                    int(c["class_id"]),
                    flat_detections,
                    pick_radius,
                )
                self.db.create_incident(
                    mission_id=mission_id,
                    class_id=int(c["class_id"]),
                    count=int(c["count"]),
                    avg_conf=float(c["avg_conf"]),
                    lat=float(c["lat"]),
                    lon=float(c["lon"]),
                    best_evidence_path=best,
                )
                incident_count += 1

        det_count = len(flat_detections)
        self.db.update_mission_counters(
            mission_id,
            processed_images=processed,
            failed_images=failed,
            detection_count=det_count,
            incident_count=incident_count,
        )

        duration = time.perf_counter() - start
        self.writer.write_manifest(
            {
                "version": 1,
                "mission_id": mission_id,
                "mission_name": self.mission_name,
                "total_images": total,
                "processed_images": processed,
                "failed_images": failed,
                "detection_count": det_count,
                "incident_count": incident_count,
                "duration_seconds": round(duration, 3),
                "model_path": str(self.model_path),
                "sync_status": "pending",
            }
        )

        return ProcessingResult(
            total_images=total,
            processed_images=processed,
            failed_images=failed,
            detection_count=det_count,
            incident_count=incident_count,
            duration_seconds=duration,
            output_dir=self.output_dir,
            mission_id=mission_id,
        )

    def _process_one_image(
        self,
        *,
        mission_id: int,
        img_path: Path,
        flat_detections: List[Dict[str, Any]],
    ) -> int:
        try:
            mrk = img_path.with_suffix(".MRK")
            mrk_path = str(mrk) if mrk.is_file() else None
            meta = get_image_metadata(str(img_path), mrk_path)
        except (MetadataError, OSError, ValueError) as exc:
            raise RuntimeError(f"metadata: {exc}") from exc

        with open_image(img_path) as raw:
            w_i, h_i = raw.size
        meta.setdefault("width", w_i)
        meta.setdefault("height", h_i)

        image_id = self.db.create_image(
            mission_id=mission_id,
            filename=img_path.name,
            original_path=str(img_path.resolve()),
            gps_lat=(float(meta["lat"]) if meta.get("lat") is not None else None),
            gps_lon=(float(meta["lon"]) if meta.get("lon") is not None else None),
            altitude_y=(float(meta["rel_alt"]) if meta.get("rel_alt") is not None else None),
            yaw=(float(meta["gimbal_yaw"]) if meta.get("gimbal_yaw") is not None else None),
            width=int(meta.get("width") or w_i),
            height=int(meta.get("height") or h_i),
        )

        count = 0
        assert self._yolo is not None

        for tile, offset_x, offset_y in slice_image(
            str(img_path),
            tile_size=self.tile_size,
            overlap=self.overlap,
        ):
            self._check_interrupt()
            for cls_id, conf, x, y, w, h in self._yolo.predict(
                tile, confidence=self.confidence_threshold
            ):
                global_x = offset_x + x
                global_y = offset_y + y
                lat: Optional[float] = None
                lon: Optional[float] = None
                try:
                    lat, lon = project_pixel_to_gps(meta, global_x, global_y)
                except (ValueError, KeyError, TypeError) as exc:
                    logger.warning(
                        "Skip GPS for %s box (%.1f,%.1f): %s",
                        img_path.name,
                        global_x,
                        global_y,
                        exc,
                    )

                padding = 100
                box_x1 = int(x - w / 2)
                box_y1 = int(y - h / 2)
                box_x2 = int(x + w / 2)
                box_y2 = int(y + h / 2)
                crop_x1 = max(0, box_x1 - padding)
                crop_y1 = max(0, box_y1 - padding)
                crop_x2 = min(tile.width, box_x2 + padding)
                crop_y2 = min(tile.height, box_y2 + padding)
                evidence_img = tile.crop((crop_x1, crop_y1, crop_x2, crop_y2))
                evidence_name = f"det_{uuid.uuid4().hex}.jpg"
                evidence_rel = self.writer.save_evidence_crop(evidence_img, evidence_name)

                self.db.create_detection(
                    image_id=image_id,
                    class_id=cls_id,
                    confidence=conf,
                    image_x=global_x,
                    image_y=global_y,
                    lat=lat,
                    lon=lon,
                    evidence_path=evidence_rel,
                )
                flat_detections.append(
                    {
                        "class_id": cls_id,
                        "confidence": conf,
                        "lat": lat,
                        "lon": lon,
                        "evidence_path": evidence_rel,
                    }
                )
                count += 1

        if self.generate_l2:
            l2_name = f"{img_path.stem}_l2.jpg"
            l2_rel = self.writer.save_l2_preview(img_path, l2_name)
            self.db.update_image_l2(image_id, l2_rel)

        return count

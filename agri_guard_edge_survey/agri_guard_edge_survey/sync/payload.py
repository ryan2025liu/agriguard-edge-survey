"""
[INPUT]: Output directory, optional local mission id from SQLite.
[OUTPUT]: API manifest dict and list of (relpath, absolute Path) for multipart upload.
[POS]: Edge Survey CLI — bundle builder for POST /edge/survey/import.
[PROTOCOL]:
 1. Relative paths in manifest must match multipart filenames (POSIX).
 2. Files must exist under output_dir.
 3. Optional `target_cloud_mission_id` becomes manifest `target_mission_id` (merge into existing cloud mission).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agri_guard_edge_survey.storage.local_db import LocalDatabase


def resolve_local_mission_id(db: LocalDatabase, explicit: Optional[int]) -> int:
    if explicit is not None:
        row = db.fetch_mission_row(explicit)
        if not row:
            raise ValueError(f"No local mission with id={explicit} in results.db")
        return explicit
    rows = db.list_missions_summary()
    if not rows:
        raise ValueError("No missions in results.db; run survey process first")
    return int(rows[0]["id"])


def build_import_bundle(
    output_dir: Path,
    *,
    local_mission_id: Optional[int] = None,
    target_cloud_mission_id: Optional[int] = None,
) -> Tuple[Dict[str, Any], List[Tuple[str, Path]]]:
    output_dir = output_dir.resolve()
    db_path = output_dir / "results.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"Missing results.db under {output_dir}")

    db = LocalDatabase(db_path)
    mid = resolve_local_mission_id(db, local_mission_id)
    mrow = db.fetch_mission_row(mid)
    assert mrow is not None

    images_out: List[Dict[str, Any]] = []
    for im in db.fetch_images_for_mission(mid):
        images_out.append(
            {
                "local_id": int(im["id"]),
                "filename": im["filename"],
                "gps_lat": im["gps_lat"],
                "gps_lon": im["gps_lon"],
                "width": im["width"],
                "height": im["height"],
                "l2_relpath": im["l2_path"],
            }
        )

    detections_out: List[Dict[str, Any]] = []
    for det in db.fetch_detections_for_mission(mid):
        detections_out.append(
            {
                "local_image_id": int(det["image_id"]),
                "class_id": int(det["class_id"]),
                "confidence": float(det["confidence"]),
                "image_x": float(det["image_x"]),
                "image_y": float(det["image_y"]),
                "lat": det["lat"],
                "lon": det["lon"],
                "evidence_relpath": det["evidence_path"],
            }
        )

    incidents_out: List[Dict[str, Any]] = []
    for inc in db.fetch_incidents_for_mission_rows(mid):
        incidents_out.append(
            {
                "class_id": int(inc["class_id"]),
                "count": int(inc["count"]),
                "avg_conf": float(inc["avg_conf"]),
                "lat": float(inc["lat"]),
                "lon": float(inc["lon"]),
                "best_evidence_relpath": inc["best_evidence_path"],
            }
        )

    lat_vals = [float(i["lat"]) for i in incidents_out if i.get("lat") is not None]
    lon_vals = [float(i["lon"]) for i in incidents_out if i.get("lon") is not None]
    base_lat = sum(lat_vals) / len(lat_vals) if lat_vals else None
    base_lon = sum(lon_vals) / len(lon_vals) if lon_vals else None

    manifest: Dict[str, Any] = {
        "version": 1,
        "local_mission_id": mid,
        "mission_name": mrow["name"],
        "description": "Imported via Edge Survey CLI",
        "base_lat": base_lat,
        "base_lon": base_lon,
        "model_path": mrow["model_path"],
        "images": images_out,
        "detections": detections_out,
        "incidents": incidents_out,
    }
    if target_cloud_mission_id is not None:
        manifest["target_mission_id"] = int(target_cloud_mission_id)

    file_paths: Dict[str, Path] = {}
    for rel_key in _collect_rel_paths(manifest):
        abs_path = output_dir / rel_key
        if not abs_path.is_file():
            raise FileNotFoundError(f"Missing artifact file: {abs_path}")
        file_paths[rel_key] = abs_path

    ordered = sorted(file_paths.items(), key=lambda x: x[0])
    return manifest, ordered


def _collect_rel_paths(manifest: Dict[str, Any]) -> List[str]:
    paths: List[str] = []
    for im in manifest.get("images") or []:
        p = im.get("l2_relpath")
        if p:
            paths.append(str(p).replace("\\", "/").lstrip("/"))
    for d in manifest.get("detections") or []:
        p = d.get("evidence_relpath")
        if p:
            paths.append(str(p).replace("\\", "/").lstrip("/"))
    for i in manifest.get("incidents") or []:
        p = i.get("best_evidence_relpath")
        if p:
            paths.append(str(p).replace("\\", "/").lstrip("/"))
    return sorted(set(paths))

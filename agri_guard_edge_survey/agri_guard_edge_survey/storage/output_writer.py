"""
[INPUT]: Output root directory, PIL crops, source image paths.
[OUTPUT]: Relative paths (posix) under output root for DB references.
[POS]: Filesystem layout for evidence and L2 previews.
[PROTOCOL]:
 1. Never copy raw originals — only generated JPEG artifacts.
 2. Return relative paths with forward slashes for cross-platform DB consistency.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Union

from agri_guard_core.pil_open import open_image
from PIL import Image

PathLike = Union[str, Path]


class OutputWriter:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.resolve()
        self.evidence_dir = self.output_dir / "evidence"
        self.l2_dir = self.output_dir / "l2_previews"
        self.logs_dir = self.output_dir / "logs"

    def ensure_layout(self) -> None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.l2_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def rel_path(self, absolute: Path) -> str:
        rel = absolute.resolve().relative_to(self.output_dir)
        return rel.as_posix()

    def save_evidence_crop(self, crop: Image.Image, filename: str) -> str:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        dest = self.evidence_dir / filename
        img = crop
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(dest, format="JPEG", quality=85)
        return self.rel_path(dest)

    def save_l2_preview(self, source_image: Path, dest_name: str) -> str:
        self.l2_dir.mkdir(parents=True, exist_ok=True)
        dest = self.l2_dir / dest_name
        with open_image(source_image) as full_img:
            img = full_img.copy()
            img.thumbnail((1920, 1920))
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(dest, format="JPEG", quality=60, optimize=True)
        return self.rel_path(dest)

    def write_manifest(self, data: Dict[str, Any]) -> Path:
        payload = {
            **data,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self.output_dir / "manifest.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

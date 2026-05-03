"""
[INPUT]: N/A
[OUTPUT]: `open_image` — bound to Pillow's real `Image.open` at import time.
[POS]: Used by metadata/tiling (and edge pipeline) so JPEG/EXIF I/O does not go through
        Ultralytics' monkey-patch on `PIL.Image.open` (which routes some paths via HEIF and
        requires optional native deps like libheif / pi-heif).
[PROTOCOL]:
 1. Import this module before `ultralytics` is imported for the first time (edge `pipeline`
    imports `agri_guard_core.metadata` before `CachedYoloRunner.predict`).
 2. For true `.heic`/`.heif` files, install Pillow-HEIF stack separately or use unpatched path only
    after adding optional deps.
"""

from __future__ import annotations

from PIL import Image

# Captured once; Ultralytics later replaces `Image.open` on the module.
open_image = Image.open

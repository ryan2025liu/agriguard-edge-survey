"""
[INPUT]: SQLite path under output directory; row fields for missions/images/detections/incidents.
[OUTPUT]: Persistent local results for one `survey process` run.
[POS]: Offline-first storage before Phase 2 cloud sync.
[PROTOCOL]:
 1. Paths inside DB are relative to output root (e.g. evidence/foo.jpg).
 2. Use INTEGER for IDs; JSON config stored as TEXT.
 3. **Always close** connections: native `sqlite3.Connection` as `with conn` does not call `close()` — use `connect()` contextmanager below.
 4. **`missions.sync_target_mission_id`**: user’s first chosen cloud merge target for this import; `NULL` = not locked yet; **`-1`** = locked to **create new** cloud mission; **positive** = locked to merge into that mission id. Prevents accidental mixed uploads on resume.
 5. **`edge_session_*` columns**: after each successful batch staging POST, persist session id / api_base / counts so interrupt or 502 after 100%% still allows auto-resume without re-uploading.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    total_images INTEGER DEFAULT 0,
    processed_images INTEGER DEFAULT 0,
    failed_images INTEGER DEFAULT 0,
    detection_count INTEGER DEFAULT 0,
    incident_count INTEGER DEFAULT 0,
    model_path TEXT,
    config TEXT,
    sync_status TEXT DEFAULT 'pending',
    cloud_mission_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    synced_at TEXT,
    sync_target_mission_id INTEGER,
    edge_session_id TEXT,
    edge_session_api_base TEXT,
    edge_staging_uploaded INTEGER DEFAULT 0,
    edge_staging_required INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_path TEXT,
    l2_path TEXT,
    gps_lat REAL,
    gps_lon REAL,
    altitude_y REAL,
    yaw REAL,
    width INTEGER,
    height INTEGER,
    status TEXT DEFAULT 'done',
    error_message TEXT,
    FOREIGN KEY (mission_id) REFERENCES missions(id)
);

CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL,
    class_id INTEGER,
    confidence REAL,
    image_x REAL,
    image_y REAL,
    lat REAL,
    lon REAL,
    evidence_path TEXT,
    FOREIGN KEY (image_id) REFERENCES images(id)
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER NOT NULL,
    class_id INTEGER,
    count INTEGER,
    avg_conf REAL,
    lat REAL,
    lon REAL,
    best_evidence_path TEXT,
    verification_status TEXT DEFAULT 'UNVERIFIED',
    FOREIGN KEY (mission_id) REFERENCES missions(id)
);

CREATE INDEX IF NOT EXISTS idx_images_mission ON images(mission_id);
CREATE INDEX IF NOT EXISTS idx_detections_image ON detections(image_id);
CREATE INDEX IF NOT EXISTS idx_incidents_mission ON incidents(mission_id);
"""


@dataclass
class LocalDatabase:
    db_path: Path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            self._ensure_missions_columns(conn)
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _ensure_missions_columns(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(missions)").fetchall()}
        if "sync_target_mission_id" not in cols:
            conn.execute(
                "ALTER TABLE missions ADD COLUMN sync_target_mission_id INTEGER"
            )
            conn.commit()
        for col, ddl in (
            ("edge_session_id", "ALTER TABLE missions ADD COLUMN edge_session_id TEXT"),
            (
                "edge_session_api_base",
                "ALTER TABLE missions ADD COLUMN edge_session_api_base TEXT",
            ),
            (
                "edge_staging_uploaded",
                "ALTER TABLE missions ADD COLUMN edge_staging_uploaded INTEGER DEFAULT 0",
            ),
            (
                "edge_staging_required",
                "ALTER TABLE missions ADD COLUMN edge_staging_required INTEGER DEFAULT 0",
            ),
        ):
            cols = {row[1] for row in conn.execute("PRAGMA table_info(missions)").fetchall()}
            if col not in cols:
                conn.execute(ddl)
                conn.commit()

    def init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def create_mission(
        self,
        name: str,
        total_images: int,
        model_path: str,
        config: Dict[str, Any],
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO missions (name, total_images, model_path, config)
                VALUES (?, ?, ?, ?)
                """,
                (name, total_images, model_path, json.dumps(config)),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_mission_counters(
        self,
        mission_id: int,
        *,
        processed_images: Optional[int] = None,
        failed_images: Optional[int] = None,
        detection_count: Optional[int] = None,
        incident_count: Optional[int] = None,
    ) -> None:
        fields = []
        values: List[Any] = []
        if processed_images is not None:
            fields.append("processed_images = ?")
            values.append(processed_images)
        if failed_images is not None:
            fields.append("failed_images = ?")
            values.append(failed_images)
        if detection_count is not None:
            fields.append("detection_count = ?")
            values.append(detection_count)
        if incident_count is not None:
            fields.append("incident_count = ?")
            values.append(incident_count)
        if not fields:
            return
        values.append(mission_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE missions SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()

    def create_image(
        self,
        mission_id: int,
        filename: str,
        original_path: str,
        gps_lat: Optional[float],
        gps_lon: Optional[float],
        altitude_y: Optional[float],
        yaw: Optional[float],
        width: Optional[int],
        height: Optional[int],
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO images (
                  mission_id, filename, original_path, gps_lat, gps_lon,
                  altitude_y, yaw, width, height, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'done')
                """,
                (
                    mission_id,
                    filename,
                    original_path,
                    gps_lat,
                    gps_lon,
                    altitude_y,
                    yaw,
                    width,
                    height,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def mark_image_error(self, image_id: int, message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE images SET status = 'error', error_message = ?
                WHERE id = ?
                """,
                (message[:2000], image_id),
            )
            conn.commit()

    def update_image_l2(self, image_id: int, l2_relative: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE images SET l2_path = ? WHERE id = ?",
                (l2_relative, image_id),
            )
            conn.commit()

    def update_image_dimensions(self, image_id: int, width: int, height: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE images SET width = ?, height = ? WHERE id = ?",
                (width, height, image_id),
            )
            conn.commit()

    def create_detection(
        self,
        image_id: int,
        class_id: int,
        confidence: float,
        image_x: float,
        image_y: float,
        lat: Optional[float],
        lon: Optional[float],
        evidence_path: Optional[str],
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO detections (
                  image_id, class_id, confidence, image_x, image_y,
                  lat, lon, evidence_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    image_id,
                    class_id,
                    confidence,
                    image_x,
                    image_y,
                    lat,
                    lon,
                    evidence_path,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def create_incident(
        self,
        mission_id: int,
        class_id: int,
        count: int,
        avg_conf: float,
        lat: float,
        lon: float,
        best_evidence_path: Optional[str],
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO incidents (
                  mission_id, class_id, count, avg_conf, lat, lon, best_evidence_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mission_id,
                    class_id,
                    count,
                    avg_conf,
                    lat,
                    lon,
                    best_evidence_path,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def delete_incidents_for_mission(self, mission_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM incidents WHERE mission_id = ?", (mission_id,))
            conn.commit()

    def fetch_detections_for_mission(self, mission_id: int) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT d.* FROM detections d
                    JOIN images i ON i.id = d.image_id
                    WHERE i.mission_id = ?
                    """,
                    (mission_id,),
                ).fetchall()
            )

    def fetch_mission_row(self, mission_id: int) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
            return row

    def list_missions_summary(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, created_at, processed_images, failed_images,
                       detection_count, incident_count, sync_status, model_path,
                       sync_target_mission_id, cloud_mission_id
                FROM missions ORDER BY id DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def fetch_images_for_mission(self, mission_id: int) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM images WHERE mission_id = ? ORDER BY id ASC",
                    (mission_id,),
                ).fetchall()
            )

    def fetch_incidents_for_mission_rows(self, mission_id: int) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM incidents WHERE mission_id = ? ORDER BY id ASC",
                    (mission_id,),
                ).fetchall()
            )

    def update_mission_cloud_sync(
        self,
        mission_id: int,
        cloud_mission_id: int,
        status: str = "synced",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE missions
                SET cloud_mission_id = ?, sync_status = ?,
                    synced_at = datetime('now'),
                    edge_session_id = NULL, edge_session_api_base = NULL,
                    edge_staging_uploaded = 0, edge_staging_required = 0
                WHERE id = ?
                """,
                (cloud_mission_id, status, mission_id),
            )
            conn.commit()

    def save_edge_staging_checkpoint(
        self,
        mission_id: int,
        *,
        session_id: str,
        api_base: str,
        uploaded: int,
        required: int,
    ) -> None:
        """Persist batch staging progress after each successful POST .../files."""
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE missions SET
                    edge_session_id = ?,
                    edge_session_api_base = ?,
                    edge_staging_uploaded = ?,
                    edge_staging_required = ?
                WHERE id = ?
                """,
                (session_id, api_base, uploaded, required, mission_id),
            )
            conn.commit()

    def clear_edge_staging_checkpoint(self, mission_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE missions SET
                    edge_session_id = NULL, edge_session_api_base = NULL,
                    edge_staging_uploaded = 0, edge_staging_required = 0
                WHERE id = ?
                """,
                (mission_id,),
            )
            conn.commit()

    def set_sync_target_mission_lock(
        self,
        mission_id: int,
        *,
        target_cloud_mission_id: Optional[int],
    ) -> None:
        """
        Lock cloud import intent: None -> -1 (create new mission);
        int -> merge into that cloud mission id.
        """
        lock_val = -1 if target_cloud_mission_id is None else int(target_cloud_mission_id)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE missions SET sync_target_mission_id = ?
                WHERE id = ?
                """,
                (lock_val, mission_id),
            )
            conn.commit()

    def clear_sync_target_mission_lock(self, mission_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE missions SET sync_target_mission_id = NULL WHERE id = ?",
                (mission_id,),
            )
            conn.commit()

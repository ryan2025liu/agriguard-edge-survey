"""
[INPUT]: API base URL, bearer token, manifest dict, list of (relpath, path).
[OUTPUT]: Parsed JSON response from POST /edge/survey/import, or ping JSON.
[POS]: HTTPS client for Edge Survey sync (Phase 2 + Phase 3 chunked sessions).
[PROTOCOL]:
 1. Use Authorization: Bearer <token> (same JWT as web frontend when token-based auth is enabled).
 2. Retries: optional for HTTP 429 / 502 / 503 / 504 with linear backoff (rebuild multipart each attempt).
 3. **Do not** `open()` all bundle files at once — large syncs exceed `ulimit`; read each path into memory sequentially (peak RAM ≈ bundle size per **monolithic** request; chunked path uses one batch at a time).
 4. format_import_error surfaces FastAPI `detail` (string or validation list) clearly.
 5. Chunked: `POST /edge/survey/import/batch/session` + `/files` batches + `/finalize`; state file `.edge_survey_sync_state.json`; **auto-resume** when state file exists (even without `--resume`) or when SQLite has `edge_session_id`; **per-batch checkpoint** to SQLite. **If GET session is already COMPLETED**, heal local DB and return without re-upload.
 6. **Repair-first**: with no active batch session, if `manifest.target_mission_id` is set, try `POST .../import/repair-from-storage` (gzip JSON); on **200** return (skip staging upload); on **409** (OSS missing) fall through to normal batch session. **Read timeout** uses `max(sync timeout, SURVEY_BATCH_SESSION_TIMEOUT, SURVEY_REPAIR_TIMEOUT)` (default repair 3600s).
 7. **`fetch_mission_snapshot`**: GET `/missions/{id}` after sync for `total_images` / `total_detections` display in CLI statistics block.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

RETRY_STATUS = frozenset({429, 502, 503, 504})

SYNC_STATE_FILENAME = ".edge_survey_sync_state.json"
AUTO_CHUNK_MIN_FILES = 500
AUTO_CHUNK_MIN_BYTES = 40 * 1024 * 1024
DEFAULT_BATCH_SESSION_TIMEOUT_SEC = int(
    os.getenv("SURVEY_BATCH_SESSION_TIMEOUT", "900")
)
# Repair waits for server list + DB persist; default higher than generic sync timeout.
DEFAULT_REPAIR_READ_TIMEOUT_SEC = int(
    os.getenv("SURVEY_REPAIR_TIMEOUT", "3600")
)


def get_edge_survey_ping(api_base_url: str, *, timeout: int = 15) -> Dict[str, Any]:
    root = api_base_url.strip().rstrip("/")
    url = f"{root}/edge/survey/ping"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"ping request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(format_import_error(resp.status_code, resp))
    ctype = (resp.headers.get("Content-Type") or "").lower()
    looks_html = "html" in ctype or (resp.text or "").lstrip().lower().startswith("<!doctype")
    if looks_html:
        raise RuntimeError(
            "ping reached an HTML page (SPA / static site), not the FastAPI API. "
            f"Requested URL was {url!r}. "
            "Fix SURVEY_API_BASE_URL: try the same origin your browser uses for API calls "
            "(often without /api if Nginx strips that prefix to the backend), "
            "or use an internal API host. Open the URL in a browser — you should see JSON like "
            '{"ok":true,"service":"edge_survey"}, not HTML.'
        )
    try:
        return resp.json()
    except Exception as exc:
        raise RuntimeError(f"ping: non-JSON response HTTP {resp.status_code}: {resp.text[:500]}") from exc


def format_import_error(status: int, resp: requests.Response) -> str:
    raw = resp.text or ""
    if status == 524 or (
        status >= 500
        and raw
        and "524" in raw
        and "cloudflare" in raw.lower()
    ):
        return (
            f"HTTP {status}: Cloudflare / CDN timeout waiting for origin "
            f"(often huge manifest on POST .../batch/session). "
            f"Deploy API gzip support for that route, raise proxy_read_timeout, "
            f"or use direct API URL; CLI uses gzip + SURVEY_BATCH_SESSION_TIMEOUT."
        )
    try:
        data = resp.json()
    except Exception:
        return f"HTTP {status}: {raw[:2000]}"

    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str):
            return f"HTTP {status}: {detail}"
        if isinstance(detail, list):
            parts = []
            for item in detail[:20]:
                if isinstance(item, dict):
                    loc = item.get("loc", [])
                    msg = item.get("msg", "")
                    parts.append(f"{'/'.join(str(x) for x in loc)}: {msg}")
                else:
                    parts.append(str(item))
            more = " …" if len(detail) > 20 else ""
            return f"HTTP {status} validation: {'; '.join(parts)}{more}"
        err = data.get("errors")
        if err is not None:
            return f"HTTP {status}: {json.dumps(err, ensure_ascii=False)[:2000]}"
        return f"HTTP {status}: {json.dumps(data, ensure_ascii=False)[:2000]}"

    return f"HTTP {status}: {raw[:2000]}"


def norm_relpath(rel: str) -> str:
    return str(rel).replace("\\", "/").lstrip("/")


def should_use_chunked_import(
    files: List[Tuple[str, Path]],
    *,
    force_chunked: bool,
    force_monolithic: bool,
) -> bool:
    if force_monolithic:
        return False
    if force_chunked:
        return True
    total_bytes = sum(path.stat().st_size for _, path in files)
    return len(files) >= AUTO_CHUNK_MIN_FILES or total_bytes >= AUTO_CHUNK_MIN_BYTES


def iter_upload_batches(
    files: List[Tuple[str, Path]],
    *,
    max_files: int,
    max_bytes: int,
) -> List[List[Tuple[str, Path]]]:
    batches: List[List[Tuple[str, Path]]] = []
    cur: List[Tuple[str, Path]] = []
    cur_b = 0
    for rel, path in files:
        sz = path.stat().st_size
        if cur and (len(cur) >= max_files or cur_b + sz > max_bytes):
            batches.append(cur)
            cur = []
            cur_b = 0
        cur.append((rel, path))
        cur_b += sz
    if cur:
        batches.append(cur)
    return batches


def _auth_headers(bearer_token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {bearer_token.strip()}"}


def fetch_mission_snapshot(
    api_base_url: str,
    bearer_token: str,
    mission_id: int,
    *,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    GET ``/missions/{id}`` — used after sync to show cloud-side totals (``total_images``, etc.).
    """
    root = api_base_url.strip().rstrip("/")
    url = f"{root}/missions/{int(mission_id)}"
    try:
        resp = requests.get(
            url,
            headers=_auth_headers(bearer_token),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(format_import_error(resp.status_code, resp))
    try:
        return resp.json()
    except Exception as exc:
        raise RuntimeError(
            f"GET mission HTTP {resp.status_code} is not JSON: {resp.text[:500]}"
        ) from exc


def _parse_json_response(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception as exc:
        raise RuntimeError(
            f"HTTP {resp.status_code} but response is not JSON: {resp.text[:500]}"
        ) from exc


def try_repair_edge_survey_from_storage(
    api_base_url: str,
    bearer_token: str,
    manifest: Dict[str, Any],
    *,
    timeout: int = 600,
    max_retries: int = 2,
    retry_backoff_sec: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """
    POST ``/edge/survey/import/repair-from-storage`` (gzip JSON, same as batch session create).

    Returns the import-shaped JSON on success. Returns ``None`` on HTTP **409** (objects
    missing in storage — caller should run normal chunked upload).
    """
    root = api_base_url.strip().rstrip("/")
    url = f"{root}/edge/survey/import/repair-from-storage"
    headers = _auth_headers(bearer_token)
    raw_json = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    payload = gzip.compress(raw_json, compresslevel=6)
    extra = {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
    }
    attempts = max(1, max_retries + 1)
    last: requests.Response | None = None
    for attempt in range(attempts):
        try:
            resp = requests.post(
                url,
                data=payload,
                headers={**headers, **extra},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"POST repair-from-storage failed: {exc}") from exc
        last = resp
        if resp.status_code == 409:
            return None
        if resp.status_code < 400:
            return _parse_json_response(resp)
        if resp.status_code not in RETRY_STATUS or attempt >= attempts - 1:
            raise RuntimeError(format_import_error(resp.status_code, resp))
        wait = retry_backoff_sec * (attempt + 1)
        logger.warning("repair-from-storage HTTP %s, retry in %.1fs", resp.status_code, wait)
        time.sleep(wait)
    assert last is not None
    raise RuntimeError(format_import_error(last.status_code, last))


def post_edge_survey_import_chunked(
    api_base_url: str,
    bearer_token: str,
    manifest: Dict[str, Any],
    files: List[Tuple[str, Path]],
    *,
    state_path: Path,
    resume: bool,
    timeout: int = 600,
    max_retries: int = 2,
    retry_backoff_sec: float = 2.0,
    progress: Optional[Callable[[str], None]] = None,
    on_staging_progress: Optional[Callable[[str, str, int, int], None]] = None,
    mission_edge_session_id: Optional[str] = None,
    mission_edge_api_base: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create batch session, upload files in chunks, finalize.

    Reuses an existing session when the state file or SQLite ``edge_session_id`` (for
    this API base) refers to a **PENDING** server session. If the server reports
    **COMPLETED**, returns a minimal dict with ``mission_id`` (no re-upload).
    """
    root = api_base_url.strip().rstrip("/")
    headers = _auth_headers(bearer_token)
    attempts = max(1, max_retries + 1)
    local_mid = manifest.get("local_mission_id")

    def log(msg: str) -> None:
        if progress:
            progress(msg)
        else:
            logger.info("%s", msg)

    def _checkpoint(sid: str, uploaded: int, required: int) -> None:
        if on_staging_progress is not None and required >= 0:
            on_staging_progress(sid, root, uploaded, required)

    def _write_state_file(sid: str) -> None:
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "session_id": sid,
                    "api_base": root,
                    "local_mission_id": local_mid,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def _raise_for_status(resp: requests.Response) -> None:
        if resp.status_code < 400:
            return
        raise RuntimeError(format_import_error(resp.status_code, resp))

    def _request_json_with_retry(
        method: str,
        url: str,
        *,
        timeout_sec: float | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        t = float(timeout_sec) if timeout_sec is not None else float(timeout)
        req_headers = dict(headers)
        extra = kwargs.pop("headers", None)
        if extra:
            req_headers.update(extra)
        last: requests.Response | None = None
        for attempt in range(attempts):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=req_headers,
                    timeout=t,
                    **kwargs,
                )
            except requests.RequestException as exc:
                raise RuntimeError(f"{method} {url} failed: {exc}") from exc
            last = resp
            if resp.status_code < 400:
                return resp
            if resp.status_code not in RETRY_STATUS or attempt >= attempts - 1:
                _raise_for_status(resp)
            wait = retry_backoff_sec * (attempt + 1)
            logger.warning("HTTP %s, retry in %.1fs", resp.status_code, wait)
            time.sleep(wait)
        assert last is not None
        _raise_for_status(last)
        return last

    max_batch_files = 200
    max_batch_bytes = 50 * 1024 * 1024
    session_id: str | None = None
    to_upload = list(files)

    def _apply_pending_detail(body: Dict[str, Any], sid: str) -> None:
        nonlocal max_batch_files, max_batch_bytes, to_upload, session_id
        session_id = sid
        missing = set(body.get("missing_relpaths") or [])
        max_batch_files = int(body.get("max_batch_files", max_batch_files))
        max_batch_bytes = int(body.get("max_batch_bytes", max_batch_bytes))
        to_upload = [
            (rel, path) for rel, path in files if norm_relpath(rel) in missing
        ]
        log(
            f"Resume session {session_id}: {len(to_upload)} files remaining "
            f"(of {len(files)} local)."
        )
        uf = int(body.get("uploaded_files") or 0)
        mf = int(body.get("missing_files") or 0)
        rf = int(body.get("required_files") or (uf + mf))
        if rf > 0:
            log(
                f"Server staging: {uf}/{rf} files ({100.0 * uf / rf:.1f}%), "
                f"{mf} still missing before this run."
            )
        _checkpoint(session_id, uf, rf)

    state_sid: str | None = None
    if state_path.is_file():
        try:
            st = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid sync state file {state_path}: {exc}") from exc
        cand = st.get("session_id")
        if cand:
            if st.get("api_base") != root:
                raise RuntimeError(
                    "Stale sync state (api_base mismatch); remove "
                    f"{SYNC_STATE_FILENAME} or use matching --api-url."
                )
            if local_mid is not None and st.get("local_mission_id") != local_mid:
                raise RuntimeError(
                    "Stale sync state (local_mission_id mismatch); remove state file "
                    "or match mission."
                )
            state_sid = str(cand)

    db_base = (mission_edge_api_base or "").strip().rstrip("/")
    db_sid = (
        str(mission_edge_session_id).strip()
        if mission_edge_session_id and db_base == root
        else None
    )
    active_sid = state_sid or db_sid

    if resume and active_sid is None:
        raise RuntimeError(
            f"Cannot --resume: no {SYNC_STATE_FILENAME} and no SQLite edge_session_id "
            f"for this API base ({root!r})."
        )

    if active_sid is not None:
        url_g = f"{root}/edge/survey/import/batch/session/{active_sid}?detail=true"
        resp_g = _request_json_with_retry("GET", url_g)
        body_g = _parse_json_response(resp_g)
        st_g = body_g.get("status")
        mid_done = body_g.get("mission_id")
        if st_g == "COMPLETED" and mid_done is not None:
            try:
                state_path.unlink(missing_ok=True)
            except OSError:
                pass
            stored = int(body_g.get("uploaded_files") or 0)
            log(
                f"Session {active_sid} already COMPLETED on server "
                f"(cloud mission_id={mid_done}); skipping re-upload."
            )
            return {
                "mission_id": int(mid_done),
                "images_created": 0,
                "detections_created": 0,
                "incidents_created": 0,
                "files_stored": stored,
            }
        if st_g == "PENDING":
            if state_sid is None and db_sid is not None:
                log(
                    f"Recovered batch session {active_sid} from SQLite checkpoint "
                    f"(writing {SYNC_STATE_FILENAME})."
                )
                _write_state_file(active_sid)
            _apply_pending_detail(body_g, active_sid)
        else:
            raise RuntimeError(
                f"Session {active_sid} is not usable (status={st_g!r}). "
                f"Remove {SYNC_STATE_FILENAME} and clear edge_session_* in SQLite "
                "(e.g. --reset-sync-target) or start a new upload after server TTL."
            )
    else:
        tid = manifest.get("target_mission_id")
        if tid is not None:
            log(
                "No active batch session: trying repair-from-storage "
                f"(target_mission_id={tid})..."
            )
            repair_timeout = max(
                int(timeout),
                DEFAULT_BATCH_SESSION_TIMEOUT_SEC,
                DEFAULT_REPAIR_READ_TIMEOUT_SEC,
            )
            repaired = try_repair_edge_survey_from_storage(
                root,
                bearer_token,
                manifest,
                timeout=repair_timeout,
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff_sec,
            )
            if repaired is not None:
                try:
                    state_path.unlink(missing_ok=True)
                except OSError:
                    pass
                log(
                    "repair-from-storage succeeded; skipping staging upload "
                    f"(mission_id={repaired.get('mission_id')})."
                )
                return repaired
            log(
                "repair-from-storage not applicable (e.g. OSS missing); "
                "creating batch session..."
            )
        url = f"{root}/edge/survey/import/batch/session"
        raw_json = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        payload = gzip.compress(raw_json, compresslevel=6)
        session_timeout = max(
            float(timeout),
            float(DEFAULT_BATCH_SESSION_TIMEOUT_SEC),
        )
        log(
            f"Creating batch session (manifest JSON {len(raw_json)} B, "
            f"gzip {len(payload)} B, read timeout {session_timeout:.0f}s)..."
        )
        resp = _request_json_with_retry(
            "POST",
            url,
            timeout_sec=session_timeout,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
            },
        )
        body = _parse_json_response(resp)
        sid_new = body.get("session_id")
        if not sid_new:
            raise RuntimeError("batch session response missing session_id")
        session_id = str(sid_new)
        max_batch_files = int(body.get("max_batch_files", max_batch_files))
        max_batch_bytes = int(body.get("max_batch_bytes", max_batch_bytes))
        req_n = int(body.get("required_relpaths_count") or len(files))
        _write_state_file(session_id)
        _checkpoint(session_id, 0, req_n)
        log(
            f"Created batch session {session_id} "
            f"(batches up to {max_batch_files} files / {max_batch_bytes} bytes)."
        )

    assert session_id is not None
    batches = iter_upload_batches(
        to_upload, max_files=max_batch_files, max_bytes=max_batch_bytes
    )
    for i, batch in enumerate(batches, start=1):
        multipart: List[Tuple[str, Tuple[str, Any, str]]] = []
        try:
            for rel, path in batch:
                norm = norm_relpath(rel)
                blob = path.read_bytes()
                multipart.append(
                    ("files", (norm, io.BytesIO(blob), "image/jpeg")),
                )
        except OSError as exc:
            if exc.errno == 24:
                raise RuntimeError(
                    "Too many open files during chunked upload. Try: ulimit -n 65536"
                ) from exc
            raise
        url_f = f"{root}/edge/survey/import/batch/session/{session_id}/files"
        last_resp: requests.Response | None = None
        for attempt in range(attempts):
            try:
                resp = requests.post(
                    url_f,
                    files=multipart,
                    headers=headers,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                raise RuntimeError(f"batch upload failed: {exc}") from exc
            last_resp = resp
            if resp.status_code < 400:
                break
            if resp.status_code not in RETRY_STATUS or attempt >= attempts - 1:
                _raise_for_status(resp)
            wait = retry_backoff_sec * (attempt + 1)
            logger.warning("Batch HTTP %s, retry in %.1fs", resp.status_code, wait)
            time.sleep(wait)
            multipart = []
            for rel, path in batch:
                norm = norm_relpath(rel)
                blob = path.read_bytes()
                multipart.append(
                    ("files", (norm, io.BytesIO(blob), "image/jpeg")),
                )
        assert last_resp is not None
        info = _parse_json_response(last_resp)
        st = int(info.get("session_files_total") or 0)
        miss = int(info.get("missing_files") or 0)
        den = st + miss
        pct = (100.0 * st / den) if den > 0 else 0.0
        log(
            f"Batch {i}/{len(batches)} — overall {pct:.1f}% "
            f"({st}/{den} files on server, {miss} left); "
            f"this batch +{info.get('batch_stored', '?')}."
        )
        if den > 0:
            _checkpoint(session_id, st, den)

    log("Finalizing session (writing mission data to cloud)...")
    url_done = f"{root}/edge/survey/import/batch/session/{session_id}/finalize"
    resp = _request_json_with_retry("POST", url_done)
    out = _parse_json_response(resp)
    try:
        state_path.unlink(missing_ok=True)
    except OSError:
        pass
    return out


def post_edge_survey_import(
    api_base_url: str,
    bearer_token: str,
    manifest: Dict[str, Any],
    files: List[Tuple[str, Path]],
    *,
    timeout: int = 600,
    max_retries: int = 2,
    retry_backoff_sec: float = 2.0,
) -> Dict[str, Any]:
    root = api_base_url.strip().rstrip("/")
    url = f"{root}/edge/survey/import"

    headers = {"Authorization": f"Bearer {bearer_token.strip()}"}

    attempts = max(1, max_retries + 1)
    last_resp: requests.Response | None = None

    for attempt in range(attempts):
        try:
            multipart: List[Tuple[str, Tuple[str, Any, str]]] = []
            for rel, path in files:
                norm = norm_relpath(rel)
                # Sequential read: opening all paths at once hits EMFILE on huge bundles (macOS ulimit).
                blob = path.read_bytes()
                multipart.append(
                    ("files", (norm, io.BytesIO(blob), "image/jpeg")),
                )
            data = {"manifest": json.dumps(manifest, ensure_ascii=False)}
            resp = requests.post(
                url,
                data=data,
                files=multipart,
                headers=headers,
                timeout=timeout,
            )
        except OSError as exc:
            if exc.errno == 24:  # EMFILE
                raise RuntimeError(
                    "Too many open files or system limit during upload build. "
                    "Try: ulimit -n 65536, or ensure sufficient free RAM for this bundle size."
                ) from exc
            raise

        last_resp = resp
        if resp.status_code < 400:
            try:
                return resp.json()
            except Exception as exc:
                raise RuntimeError(
                    f"Import HTTP {resp.status_code} but response is not JSON: {resp.text[:500]}"
                ) from exc

        if resp.status_code not in RETRY_STATUS or attempt >= attempts - 1:
            raise RuntimeError(format_import_error(resp.status_code, resp))

        wait = retry_backoff_sec * (attempt + 1)
        logger.warning(
            "Import HTTP %s, retry %s/%s in %.1fs",
            resp.status_code,
            attempt + 1,
            attempts - 1,
            wait,
        )
        time.sleep(wait)

    assert last_resp is not None
    raise RuntimeError(format_import_error(last_resp.status_code, last_resp))

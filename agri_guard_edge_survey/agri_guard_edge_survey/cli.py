"""
[INPUT]: CLI argv via Click (Typer not required).
[OUTPUT]: Process exit code; human-readable stdout / stderr.
[POS]: User-facing entry `survey` console script.
[PROTOCOL]:
 1. `process` requires `agri_guard_core`; it is declared in `pyproject.toml` (`pip install -e ./agri_guard_edge_survey` from repo root). If importing fails, install core explicitly: `pip install -e ./agri_guard_core`.
 2. **Lazy-import** `ProcessingPipeline` / `LocalDatabase` inside subcommands so `survey --version`、`ping`、`sync` do not load scipy/sklearn at startup.
 3. `sync` / `--dry-run` / `--retries` / `--target-mission-id` / **chunked import**（`--chunked`、`--no-chunked`、`--resume`、`.edge_survey_sync_state.json`、`missions.edge_session_*` 每批成功后落库）；**`--reset-sync-target`** 清除 `missions.sync_target_mission_id`、edge 暂存列与分片状态文件；菜单 **sync** 可选密码登录并选云任务；**成功结束后打印「同步统计」**（本地 manifest 条数、本次接口写入、`GET /missions/{id}` 云端 `total_images` / `total_detections` 等）；`ping`; **`survey`（无子命令）或 `survey menu`**：交互菜单（`SURVEY_CLI_LANG`、`SURVEY_*` 默认值）；`zh` / `en` 界面。
 4. See `docs/02_architecture/edge_survey_ai_cli.md`.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from typing import Any

import click

from agri_guard_edge_survey import __version__
from agri_guard_edge_survey.device import format_info_lines, resolve_device

_LOG = logging.getLogger(__name__)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="survey")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """AgriGuard edge survey image processor (local AI, no raw upload).

    Run ``survey`` with no arguments to open the interactive menu.
    """
    if ctx.invoked_subcommand is None:
        from agri_guard_edge_survey.interactive_menu import run_interactive_menu

        run_interactive_menu(cli)


@cli.command("info")
@click.option("-v", "--verbose", is_flag=True)
def info_cmd(verbose: bool) -> None:
    """Show runtime, torch, and auto-selected device."""
    _configure_logging(verbose)
    try:
        import agri_guard_core  # noqa: F401
    except ImportError:
        click.echo(
            "agri_guard_core is not installed. From repo root run:\n"
            "  pip install -e ./agri_guard_edge_survey\n"
            "Or: pip install -e ./agri_guard_core\n"
            "from the repository root.",
            err=True,
        )
        sys.exit(1)
    click.echo(format_info_lines())


@cli.command("process")
@click.option(
    "-i",
    "--input",
    "input_dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Input directory (recursively scanned for images)",
)
@click.option(
    "-o",
    "--output",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory (will contain results.db and artifacts)",
)
@click.option(
    "-m",
    "--model",
    "model_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YOLO .pt model file",
)
@click.option("--mission-name", default=None, help="Mission label stored in SQLite")
@click.option("--confidence", default=0.5, show_default=True, type=float)
@click.option("--tile-size", default=1024, show_default=True, type=int)
@click.option("--overlap", default=0.2, show_default=True, type=float)
@click.option("--cluster-eps", default=0.5, show_default=True, type=float)
@click.option(
    "--device",
    default="auto",
    type=click.Choice(["auto", "cuda", "mps", "cpu"], case_sensitive=False),
    show_default=True,
    help="Inference device; cuda maps to GPU 0",
)
@click.option(
    "--no-l2",
    is_flag=True,
    help="Do not write l2_previews/ (only evidence crops)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Delete prior results.db / manifest / artifact dirs in output",
)
@click.option("-v", "--verbose", is_flag=True)
def process_cmd(
    input_dir: Path,
    output_dir: Path,
    model_path: Path,
    mission_name: str | None,
    confidence: float,
    tile_size: int,
    overlap: float,
    cluster_eps: float,
    device: str,
    no_l2: bool,
    force: bool,
    verbose: bool,
) -> None:
    """Run slice → YOLO → geo → DBSCAN on local images."""
    _configure_logging(verbose)
    try:
        import agri_guard_core  # noqa: F401
    except ImportError:
        click.echo(
            "agri_guard_core is not installed. From repo root: pip install -e ./agri_guard_edge_survey (or pip install -e ./agri_guard_core)",
            err=True,
        )
        sys.exit(1)

    from agri_guard_edge_survey.processor.pipeline import ProcessingPipeline

    dev = resolve_device(device)
    click.echo(f"Using device: {dev}")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        pipeline = ProcessingPipeline(
            input_dir=input_dir,
            output_dir=output_dir,
            model_path=model_path,
            mission_name=mission_name,
            confidence_threshold=confidence,
            tile_size=tile_size,
            overlap=overlap,
            cluster_eps=cluster_eps,
            generate_l2=not no_l2,
            device=dev,
            force=force,
        )
        result = pipeline.run()
    except FileExistsError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    except KeyboardInterrupt:
        click.echo(
            "\nStopped (Ctrl+C). Partial results may remain in the output directory.",
            err=True,
        )
        sys.exit(130)

    click.echo("")
    click.echo("=" * 50)
    click.echo("Done")
    click.echo(f"  mission_id (local): {result.mission_id}")
    click.echo(f"  images total:       {result.total_images}")
    click.echo(f"  processed:          {result.processed_images}")
    click.echo(f"  failed:             {result.failed_images}")
    click.echo(f"  detections:         {result.detection_count}")
    click.echo(f"  incidents:          {result.incident_count}")
    click.echo(f"  duration:           {result.duration_seconds:.1f}s")
    click.echo(f"  output:             {result.output_dir}")
    click.echo("=" * 50)


@cli.command("list")
@click.option(
    "-o",
    "--output",
    "output_dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Same output directory passed to `survey process`",
)
def list_cmd(output_dir: Path) -> None:
    """Show manifest.json or SQLite mission summary."""
    from agri_guard_edge_survey.storage.local_db import LocalDatabase

    man_path = output_dir / "manifest.json"
    if man_path.is_file():
        click.echo(man_path.read_text(encoding="utf-8"))
        return
    db_path = output_dir / "results.db"
    if not db_path.is_file():
        raise click.ClickException(f"No manifest.json or results.db in {output_dir}")
    db = LocalDatabase(db_path)
    rows = db.list_missions_summary()
    if not rows:
        click.echo("No missions in results.db")
        return
    click.echo(json.dumps(rows, indent=2, ensure_ascii=False))


@cli.command("ping")
@click.option(
    "--api-url",
    envvar=["SURVEY_API_BASE_URL", "AGRI_GUARD_API_BASE_URL"],
    required=True,
    help="API base reachable from this machine, e.g. http://127.0.0.1:8000",
)
@click.option("--timeout", default=15, show_default=True, type=int)
def ping_cmd(api_url: str, timeout: int) -> None:
    """Call GET {API_BASE}/edge/survey/ping (no JWT required)."""
    try:
        from agri_guard_edge_survey.sync.client import get_edge_survey_ping
    except ImportError as exc:
        click.echo(f"requests not available: {exc}", err=True)
        sys.exit(1)
    try:
        body = get_edge_survey_ping(api_url, timeout=timeout)
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(json.dumps(body, indent=2, ensure_ascii=False))


@cli.command("sync")
@click.option(
    "-o",
    "--output",
    "output_dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Output directory from survey process (contains results.db)",
)
@click.option(
    "--local-mission-id",
    type=int,
    default=None,
    help="SQLite missions.id; default: latest row in results.db",
)
@click.option(
    "--api-url",
    envvar=["SURVEY_API_BASE_URL", "AGRI_GUARD_API_BASE_URL"],
    default=None,
    help="API root e.g. https://host or https://host/api",
)
@click.option(
    "--token",
    envvar="SURVEY_API_TOKEN",
    default=None,
    help="Bearer JWT (same as web session token)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Upload even if local DB already marked synced",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print manifest summary and file sizes only; do not upload",
)
@click.option(
    "--retries",
    default=2,
    show_default=True,
    type=int,
    help="Max extra attempts for HTTP 429 / 502 / 503 / 504",
)
@click.option(
    "--target-mission-id",
    "target_mission_id",
    type=int,
    default=None,
    envvar="SURVEY_TARGET_MISSION_ID",
    help="Merge import into this existing cloud mission (AERIAL_SURVEY, active); omit to create new",
)
@click.option(
    "--chunked",
    is_flag=True,
    help="Force batch session import (small multipart requests + finalize)",
)
@click.option(
    "--no-chunked",
    is_flag=True,
    help="Force single POST /edge/survey/import (default for small bundles)",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Force chunked mode: resume from .edge_survey_sync_state.json or SQLite edge_session_* (same API base)",
)
@click.option(
    "--forget-session",
    is_flag=True,
    help="Delete .edge_survey_sync_state.json under output and exit (no upload)",
)
@click.option(
    "--reset-sync-target",
    is_flag=True,
    help="Clear missions.sync_target_mission_id, edge staging columns, batch state file; then continue",
)
@click.option("-v", "--verbose", is_flag=True)
def sync_cmd(
    output_dir: Path,
    local_mission_id: int | None,
    api_url: str | None,
    token: str | None,
    force: bool,
    dry_run: bool,
    retries: int,
    target_mission_id: int | None,
    chunked: bool,
    no_chunked: bool,
    resume: bool,
    forget_session: bool,
    reset_sync_target: bool,
    verbose: bool,
) -> None:
    """Upload local results to AgriGuard (POST .../edge/survey/import or batch session API)."""
    _configure_logging(verbose)
    from agri_guard_edge_survey.sync.client import SYNC_STATE_FILENAME

    state_path = output_dir / SYNC_STATE_FILENAME
    if forget_session:
        try:
            state_path.unlink(missing_ok=True)
        except OSError as exc:
            click.echo(f"Could not remove state file: {exc}", err=True)
            sys.exit(1)
        click.echo(
            json.dumps(
                {"ok": True, "removed_sync_state": str(state_path)},
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if chunked and no_chunked:
        click.echo("Use either --chunked or --no-chunked, not both.", err=True)
        sys.exit(2)
    if not dry_run:
        if not api_url:
            click.echo(
                "Missing --api-url or SURVEY_API_BASE_URL / AGRI_GUARD_API_BASE_URL",
                err=True,
            )
            sys.exit(2)
        if not token:
            click.echo("Missing --token or SURVEY_API_TOKEN", err=True)
            sys.exit(2)

    try:
        from agri_guard_edge_survey.sync.client import (
            post_edge_survey_import,
            post_edge_survey_import_chunked,
            should_use_chunked_import,
        )
        from agri_guard_edge_survey.sync.payload import build_import_bundle
    except ImportError as exc:
        click.echo(f"Sync dependencies missing: {exc}", err=True)
        sys.exit(1)

    db_path = output_dir / "results.db"
    if not db_path.is_file():
        click.echo(f"No results.db under {output_dir}", err=True)
        sys.exit(1)

    from agri_guard_edge_survey.storage.local_db import LocalDatabase

    db = LocalDatabase(db_path)
    mid = local_mission_id
    if mid is None:
        rows = db.list_missions_summary()
        if not rows:
            click.echo("No mission rows in SQLite", err=True)
            sys.exit(1)
        mid = int(rows[0]["id"])

    mrow = db.fetch_mission_row(mid)
    if not mrow:
        click.echo(f"Mission id {mid} not found", err=True)
        sys.exit(1)

    def _target_to_lock_int(tid: int | None) -> int:
        return -1 if tid is None else int(tid)

    if reset_sync_target:
        db.clear_sync_target_mission_lock(mid)
        db.clear_edge_staging_checkpoint(mid)
        try:
            state_path.unlink(missing_ok=True)
        except OSError as exc:
            click.echo(f"Warning: could not remove batch state file: {exc}", err=True)
        if verbose:
            click.echo(
                f"已清除本地 mission {mid} 的 sync_target_mission_id 锁及分片状态文件。",
                err=True,
            )
        mrow = db.fetch_mission_row(mid)
        if not mrow:
            click.echo(f"Mission id {mid} not found", err=True)
            sys.exit(1)

    req_lock = _target_to_lock_int(target_mission_id)
    locked_raw = mrow["sync_target_mission_id"]
    if locked_raw is not None and int(locked_raw) != req_lock:
        def _lock_desc(v: int) -> str:
            return "新建云上航测任务" if v == -1 else f"合并到已有云上 mission_id={v}"

        click.echo(
            "拒绝同步：本地 results.db 已绑定首次云导入目标「"
            f"{_lock_desc(int(locked_raw))}」，当前为「{_lock_desc(req_lock)}」。"
            "续传请勿改目标；若确需更换，请先使用 --reset-sync-target（会删除分片续传状态）。",
            err=True,
        )
        sys.exit(2)

    if mrow["sync_status"] == "synced" and mrow["cloud_mission_id"] and not force and not dry_run:
        click.echo(
            f"Already synced to cloud mission {mrow['cloud_mission_id']}. Use --force to re-upload."
        )
        return

    if (
        target_mission_id is not None
        and mrow["cloud_mission_id"]
        and int(mrow["cloud_mission_id"]) != int(target_mission_id)
        and not force
        and not dry_run
    ):
        click.echo(
            f"Local DB cloud_mission_id={mrow['cloud_mission_id']} does not match "
            f"--target-mission-id={target_mission_id}. Use --force to override.",
            err=True,
        )
        sys.exit(2)

    try:
        manifest, file_list = build_import_bundle(
            output_dir,
            local_mission_id=mid,
            target_cloud_mission_id=target_mission_id,
        )
    except Exception as exc:
        click.echo(f"Failed to build bundle: {exc}", err=True)
        sys.exit(1)

    if dry_run:
        total_bytes = sum(p.stat().st_size for _, p in file_list)
        payload = {
            "dry_run": True,
            "output_dir": str(output_dir.resolve()),
            "local_mission_id": mid,
            "mission_name": manifest.get("mission_name"),
            "target_mission_id": manifest.get("target_mission_id"),
            "manifest_counts": {
                "images": len(manifest.get("images") or []),
                "detections": len(manifest.get("detections") or []),
                "incidents": len(manifest.get("incidents") or []),
            },
            "files": [
                {"relpath": rel, "bytes": path.stat().st_size}
                for rel, path in file_list
            ],
            "files_total": len(file_list),
            "bytes_total": total_bytes,
            "would_use_chunked": should_use_chunked_import(
                file_list,
                force_chunked=chunked,
                force_monolithic=no_chunked,
            ),
            "sync_target_mission_id": mrow["sync_target_mission_id"],
            "requested_sync_target_matches_lock": (
                mrow["sync_target_mission_id"] is None
                or int(mrow["sync_target_mission_id"]) == req_lock
            ),
        }
        if (
            (mrow["sync_status"] or "") == "synced"
            and mrow["cloud_mission_id"]
        ):
            payload["note"] = (
                f"Local DB already synced to cloud_mission_id={mrow['cloud_mission_id']}; "
                "use --force to upload again."
            )
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    assert api_url is not None and token is not None
    if mrow["sync_target_mission_id"] is None:
        db.set_sync_target_mission_lock(mid, target_cloud_mission_id=target_mission_id)

    if resume:
        api_root = api_url.strip().rstrip("/")
        m_edge_sid = mrow["edge_session_id"] if mrow["edge_session_id"] else None
        m_edge_base = (mrow["edge_session_api_base"] or "").strip().rstrip("/")
        has_state = state_path.is_file()
        has_db_ckpt = bool(m_edge_sid) and m_edge_base == api_root
        if not has_state and not has_db_ckpt:
            click.echo(
                f"No {SYNC_STATE_FILENAME} and no SQLite staging checkpoint for "
                f"this API ({api_root!r}); run sync without --resume first.",
                err=True,
            )
            sys.exit(2)
        use_chunked = True
    else:
        use_chunked = should_use_chunked_import(
            file_list,
            force_chunked=chunked,
            force_monolithic=no_chunked,
        )

    mode = "chunked batch session" if use_chunked else "single request"
    click.echo(f"Uploading mission local_id={mid} with {len(file_list)} files ({mode})...")
    try:
        if use_chunked:
            def _on_staging(
                sid: str, base: str, uploaded: int, required: int
            ) -> None:
                db.save_edge_staging_checkpoint(
                    mid,
                    session_id=sid,
                    api_base=base,
                    uploaded=uploaded,
                    required=required,
                )

            resp = post_edge_survey_import_chunked(
                api_url,
                token,
                manifest,
                file_list,
                state_path=state_path,
                resume=resume,
                max_retries=max(0, retries),
                progress=click.echo,
                on_staging_progress=_on_staging,
                mission_edge_session_id=mrow["edge_session_id"],
                mission_edge_api_base=mrow["edge_session_api_base"],
            )
        else:
            click.echo(
                "Single HTTP upload: there is no per-chunk progress; "
                "wait until the request finishes or fails.",
            )
            resp = post_edge_survey_import(
                api_url,
                token,
                manifest,
                file_list,
                max_retries=max(0, retries),
            )
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    cloud_id = int(resp.get("mission_id", 0))
    db.update_mission_cloud_sync(mid, cloud_id, status="synced")
    man_path = output_dir / "manifest.json"
    if man_path.is_file():
        try:
            md = json.loads(man_path.read_text(encoding="utf-8"))
            md["cloud_mission_id"] = cloud_id
            md["sync_status"] = "synced"
            man_path.write_text(
                json.dumps(md, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logging.getLogger(__name__).warning("manifest.json update skipped: %s", exc)

    sync_statistics: dict[str, Any] = {
        "local_bundle": {
            "images": len(manifest.get("images") or []),
            "detections": len(manifest.get("detections") or []),
            "incidents": len(manifest.get("incidents") or []),
            "files_in_bundle": len(file_list),
        },
        "this_request": {
            "images_created": int(resp.get("images_created") or 0),
            "detections_created": int(resp.get("detections_created") or 0),
            "incidents_created": int(resp.get("incidents_created") or 0),
            "files_stored": int(resp.get("files_stored") or 0),
        },
    }
    try:
        from agri_guard_edge_survey.sync.client import fetch_mission_snapshot

        cloud_snap = fetch_mission_snapshot(api_url, token, cloud_id, timeout=60)
        sync_statistics["cloud_mission_totals"] = {
            "id": cloud_snap.get("id"),
            "name": cloud_snap.get("name"),
            "mission_type": cloud_snap.get("mission_type"),
            "status": cloud_snap.get("status"),
            "total_images": cloud_snap.get("total_images"),
            "total_detections": cloud_snap.get("total_detections"),
            "total_tasks": cloud_snap.get("total_tasks"),
        }
    except RuntimeError as exc:
        sync_statistics["cloud_mission_totals_error"] = str(exc)[:800]

    click.echo("—— 同步统计 ——")
    tr = sync_statistics["this_request"]
    lb = sync_statistics["local_bundle"]
    click.echo(
        f"云端任务 ID: {cloud_id} | 本次写入: 图片 +{tr['images_created']}, "
        f"检测 +{tr['detections_created']}, 事件 +{tr['incidents_created']}, "
        f"存储文件计数 +{tr['files_stored']}"
    )
    click.echo(
        f"本地 bundle: 图片 {lb['images']}, 检测 {lb['detections']}, "
        f"事件 {lb['incidents']}, 参与上传文件 {lb['files_in_bundle']}"
    )
    cm = sync_statistics.get("cloud_mission_totals")
    if cm:
        click.echo(
            f"云端任务当前合计: 图片 {cm.get('total_images')}, "
            f"检测 {cm.get('total_detections')}"
            + (
                f", 作业点 {cm.get('total_tasks')}"
                if cm.get("total_tasks") is not None
                else ""
            )
            + (f" （{cm.get('name')}）" if cm.get("name") else "")
        )
    elif sync_statistics.get("cloud_mission_totals_error"):
        click.echo(
            "拉取云端任务汇总失败: "
            f"{sync_statistics['cloud_mission_totals_error']}",
            err=True,
        )

    click.echo(
        json.dumps(
            {
                "ok": True,
                "cloud_mission_id": cloud_id,
                "local_mission_id": mid,
                "sync_statistics": sync_statistics,
                **resp,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@cli.command("menu")
def menu_cmd() -> None:
    """Interactive prompt menu (same actions as subcommands)."""
    from agri_guard_edge_survey.interactive_menu import run_interactive_menu

    run_interactive_menu(cli)


if __name__ == "__main__":
    cli()

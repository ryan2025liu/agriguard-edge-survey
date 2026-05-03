"""
[INPUT]: The root Click `cli` group from `agri_guard_edge_survey.cli`.
[OUTPUT]: Interactive terminal menu; dispatches to same commands as CLI argv.
[POS]: Optional UX path for field users; dispatches via `cli.main()` so tqdm/logging hit the real TTY.
[PROTOCOL]:
 1. Do not duplicate business logic — build argv and `cli_group.main(args, prog_name="survey")` (not `CliRunner`, which buffers stdout until exit).
 2. Defaults come from env (`SURVEY_*`, see `.env.example`); Enter accepts the shown default.
 3. UI language: `SURVEY_CLI_LANG=zh|en` (default zh); menu `6` toggles for the session.
 4. Call `load_settings()` on entry so `.env` is applied before reading env defaults.
 5. Sync non-dry: auth mode `1` manual token / `2` POST `/token` + pick from `/missions/my-active` (AERIAL_SURVEY), **default `2`**. Non-dry sync **always passes `--chunked`** so large bundles and **repair-from-storage** (OSS already present) work without extra flags; optional `--resume` prompt.
 6. Comments in English.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from agri_guard_edge_survey.settings import load_settings, resolve_api_base_url

_STR = {
    "zh": {
        "menu_title": "—— AgriGuard 航测边缘工具 ——",
        "menu_1": "  1) info     — 设备 / PyTorch / CUDA / MPS",
        "menu_2": "  2) process  — 本地切片 → YOLO → 地理配准 → 聚类",
        "menu_3": "  3) list     — manifest / SQLite 摘要",
        "menu_4": "  4) ping     — GET .../edge/survey/ping",
        "menu_5": "  5) sync     — 上传（自动分片；OSS 已有则只补数据库）",
        "menu_6": "  6) 语言     — 切换 中文 / English",
        "menu_0": "  0) 退出",
        "select": "选择",
        "empty_select": "  （空输入 — 输入 0 退出）",
        "bye": "再见。",
        "unknown_choice": "  未知选项，请输入 0–6。",
        "bool_invalid": "  请输入 y/n 或 是/否。",
        "int_invalid": "  请输入整数。",
        "err_not_dir": "  不是目录: {path}",
        "err_not_file": "  不是文件: {path}",
        "err_sync_need_creds": "  非 dry-run 时必须填写 API 地址与 Token（或设置环境变量）。",
        "err_api_url_required": "  需要 API 根地址。",
        "exit_code": "(退出码 {code})",
        "lang_switched_zh": "  界面语言: 中文",
        "lang_switched_en": "  UI language: English",
        "info_verbose": "详细日志 (-v)",
        "process_input": "图片输入目录",
        "process_output": "输出目录",
        "process_model": "模型 .pt 路径",
        "process_mission": "任务名称（可选）",
        "process_confidence": "置信度阈值",
        "process_tile": "切片大小",
        "process_overlap": "重叠比例",
        "process_eps": "聚类 eps（米）",
        "process_device_hint": "设备: auto | cuda | mps | cpu",
        "process_device": "设备",
        "process_no_l2": "跳过 L2 预览 (--no-l2)",
        "process_force": "强制覆盖输出 DB/产物",
        "process_verbose": "详细日志",
        "list_output": "输出目录（含 manifest / results.db）",
        "ping_url": "API 根地址",
        "ping_timeout": "超时（秒）",
        "sync_output": "输出目录（含 results.db）",
        "sync_mission_id": "本地任务 id（SQLite，可空）",
        "sync_dry_run": "Dry-run（仅检查包，不上传）",
        "sync_api_url": "API 根地址",
        "sync_token": "Bearer JWT",
        "sync_force": "已同步仍强制重传",
        "sync_resume": "续传上次分片（需已有 .edge_survey_sync_state 或 SQLite 断点）",
        "sync_retries": "额外重试次数 (429/502/503/504)",
        "sync_verbose": "详细日志",
        "sync_auth_mode": "鉴权 1=粘贴 Token  2=用户名密码并选择本单位航测任务 [默认 2]",
        "login_username": "登录用户名或邮箱",
        "login_password_prompt": "登录密码",
        "login_username_required": "  需要用户名或邮箱。",
        "sync_no_active_missions": "  当前没有可选的航测活动任务（与 Web「我的活动任务」一致）。",
        "sync_pick_mission_header": "可选云任务（输入序号；将合并导入到该任务）:",
        "sync_pick_mission": "序号",
        "sync_pick_invalid": "  无效序号。",
        "sync_target_cloud_mission": "云上目标 mission id（可选，仅手写 Token 时；留空=新建任务）",
        "process_start_hint": "—— 开始执行 process（日志与 tqdm 进度在下方；Ctrl+C 一次=在下一张图/切片边界停止，连按两次=强制结束，因 GPU 单步推理可能短暂不响应）——",
        "process_exit2_hint": "  提示：退出码 2 多为输出目录里已有 results.db。可再选 2，在「强制覆盖」选 Y；或换一个空输出目录；也可手动删除该目录下的旧库后重试。",
        "sync_start_hint": "—— 开始执行 sync（网络与上传进度在下方输出）——",
    },
    "en": {
        "menu_title": "—— AgriGuard Edge Survey ——",
        "menu_1": "  1) info     — device / PyTorch / CUDA / MPS",
        "menu_2": "  2) process  — local slice → YOLO → geo → cluster",
        "menu_3": "  3) list     — manifest / SQLite summary",
        "menu_4": "  4) ping     — GET .../edge/survey/ping",
        "menu_5": "  5) sync     — upload (chunked; repair DB if OSS already has files)",
        "menu_6": "  6) Language — switch 中文 / English",
        "menu_0": "  0) exit",
        "select": "Select",
        "empty_select": "  (empty — enter 0 to exit)",
        "bye": "Bye.",
        "unknown_choice": "  Unknown choice. Enter 0–6.",
        "bool_invalid": "  Enter y/n.",
        "int_invalid": "  Invalid integer, try again.",
        "err_not_dir": "  Not a directory: {path}",
        "err_not_file": "  Not a file: {path}",
        "err_sync_need_creds": "  API URL and token are required unless dry run (or set env vars).",
        "err_api_url_required": "  API base URL required.",
        "exit_code": "(exit {code})",
        "lang_switched_zh": "  UI language: 中文",
        "lang_switched_en": "  UI language: English",
        "info_verbose": "Verbose logging (-v)",
        "process_input": "Input directory (images)",
        "process_output": "Output directory",
        "process_model": "Model .pt path",
        "process_mission": "Mission name (optional)",
        "process_confidence": "Confidence threshold",
        "process_tile": "Tile size",
        "process_overlap": "Overlap",
        "process_eps": "Cluster eps (meters)",
        "process_device_hint": "Device: auto | cuda | mps | cpu",
        "process_device": "Device",
        "process_no_l2": "Skip L2 previews (--no-l2)",
        "process_force": "Force overwrite output DB/artifacts",
        "process_verbose": "Verbose logging",
        "list_output": "Output directory (process output)",
        "ping_url": "API base URL",
        "ping_timeout": "Timeout (seconds)",
        "sync_output": "Output directory (contains results.db)",
        "sync_mission_id": "Local mission id (SQLite)",
        "sync_dry_run": "Dry run (inspect bundle only, no upload)",
        "sync_api_url": "API base URL",
        "sync_token": "Bearer JWT",
        "sync_force": "Force re-upload if already synced",
        "sync_resume": "Resume last chunked session (state file or SQLite checkpoint)",
        "sync_retries": "Extra retries (429/502/503/504)",
        "sync_verbose": "Verbose logging",
        "sync_auth_mode": "Auth: 1=Bearer token  2=username/password + pick aerial mission [default 2]",
        "login_username": "Username or email",
        "login_password_prompt": "Password",
        "login_username_required": "  Username or email required.",
        "sync_no_active_missions": "  No active AERIAL_SURVEY missions (same as web my-active).",
        "sync_pick_mission_header": "Pick cloud mission (number merges import into that mission):",
        "sync_pick_mission": "Number",
        "sync_pick_invalid": "  Invalid number.",
        "sync_target_cloud_mission": "Cloud mission id (optional, manual-token path only; empty=new mission)",
        "process_start_hint": "—— Running process (tqdm below; Ctrl+C once=stop after current image/tile; twice=force quit if GPU blocks) ——",
        "process_exit2_hint": "  Hint: exit 2 usually means results.db already exists. Re-run menu item 2 with force=Y, use an empty output dir, or remove the old DB under that dir.",
        "sync_start_hint": "—— Running sync (upload progress below) ——",
    },
}


def _normalize_lang(raw: str | None) -> str:
    if not raw:
        return "zh"
    r = raw.strip().lower().replace("_", "-")
    if r in ("zh", "zh-cn", "cn"):
        return "zh"
    if r in ("en", "en-us", "english"):
        return "en"
    return "zh"


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    s = v.strip().lower()
    if s in ("1", "true", "yes", "y", "on", "是"):
        return True
    if s in ("0", "false", "no", "n", "off", "否", ""):
        return False
    return default


def _read_line(label: str, default: str | None = None) -> str:
    if default is not None and default != "":
        suffix = f" [{default}]"
    elif default == "":
        suffix = " [Enter=empty]"
    else:
        suffix = ""
    raw = input(f"{label}{suffix}: ").strip()
    if not raw and default is not None:
        return default
    return raw


def _read_bool(label: str, default: bool, invalid_msg: str) -> bool:
    d_hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} ({d_hint}): ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes", "1", "是"):
            return True
        if raw in ("n", "no", "0", "否"):
            return False
        click.echo(invalid_msg)


def _read_int_optional(label: str, default_empty: str, invalid_msg: str) -> str:
    suffix = " [Enter=skip]" if default_empty == "" else f" [{default_empty}]"
    raw = input(f"{label}{suffix}: ").strip()
    if not raw:
        return default_empty
    try:
        int(raw)
    except ValueError:
        click.echo(invalid_msg)
        return _read_int_optional(label, default_empty, invalid_msg)
    return raw


def _expand_path(raw: str) -> Path:
    return Path(raw.strip().strip('"').strip("'")).expanduser()


def _invoke(cli_group: click.Group, args: list[str], t: dict[str, str]) -> None:
    if args:
        if args[0] == "process":
            click.echo(t["process_start_hint"])
        elif args[0] == "sync":
            click.echo(t["sync_start_hint"])
    try:
        cli_group.main(list(args), prog_name="survey", standalone_mode=True)
    except SystemExit as exc:
        code = exc.code
        if code in (0, None):
            return
        ec = code if isinstance(code, int) else 1
        click.echo(t["exit_code"].format(code=ec), err=True)
        if ec == 2 and args and args[0] == "process":
            click.echo(t["process_exit2_hint"], err=True)


def run_interactive_menu(cli_group: click.Group) -> None:
    """TTY menu loop until user exits."""
    load_settings()
    lang = _normalize_lang(os.getenv("SURVEY_CLI_LANG", "zh"))

    while True:
        t = _STR[lang]
        click.echo("")
        click.echo(t["menu_title"])
        click.echo(t["menu_1"])
        click.echo(t["menu_2"])
        click.echo(t["menu_3"])
        click.echo(t["menu_4"])
        click.echo(t["menu_5"])
        click.echo(t["menu_6"])
        click.echo(t["menu_0"])
        choice = _read_line(t["select"], "").lower()

        if choice in ("0", "q", "quit", "exit"):
            click.echo(t["bye"])
            return
        if choice == "":
            click.echo(t["empty_select"])
            continue

        if choice == "6":
            lang = "en" if lang == "zh" else "zh"
            os.environ["SURVEY_CLI_LANG"] = lang
            tn = _STR[lang]
            click.echo(tn["lang_switched_en"] if lang == "en" else tn["lang_switched_zh"])
            continue

        if choice == "1":
            verbose = _read_bool(
                t["info_verbose"],
                _env_bool("SURVEY_VERBOSE", False),
                t["bool_invalid"],
            )
            _invoke(cli_group, ["info", *(["-v"] if verbose else [])], t)
            continue

        if choice == "2":
            inp_def = os.getenv("SURVEY_INPUT_DIR", "").strip()
            out_def = os.getenv("SURVEY_OUTPUT_DIR", "").strip()
            model_def = os.getenv("SURVEY_MODEL_PATH", "").strip()

            inp_raw = _read_line(t["process_input"], inp_def or None)
            if not inp_raw:
                click.echo(t["err_not_dir"].format(path="(empty)"))
                continue
            inp = _expand_path(inp_raw)
            if not inp.is_dir():
                click.echo(t["err_not_dir"].format(path=inp))
                continue

            out_raw = _read_line(t["process_output"], out_def or None)
            if not out_raw:
                click.echo(t["err_not_dir"].format(path="(empty)"))
                continue
            out = _expand_path(out_raw)

            model_raw = _read_line(t["process_model"], model_def or None)
            if not model_raw:
                click.echo(t["err_not_file"].format(path="(empty)"))
                continue
            model = _expand_path(model_raw)
            if not model.is_file():
                click.echo(t["err_not_file"].format(path=model))
                continue

            mission_def = os.getenv("SURVEY_MISSION_NAME", "")
            mission = _read_line(t["process_mission"], mission_def)

            conf_s = _read_line(
                t["process_confidence"],
                os.getenv("SURVEY_CONFIDENCE", "0.5").strip() or "0.5",
            )
            tile_s = _read_line(
                t["process_tile"],
                os.getenv("SURVEY_TILE_SIZE", "1024").strip() or "1024",
            )
            overlap_s = _read_line(
                t["process_overlap"],
                os.getenv("SURVEY_OVERLAP", "0.2").strip() or "0.2",
            )
            eps_s = _read_line(
                t["process_eps"],
                os.getenv("SURVEY_CLUSTER_EPS", "0.5").strip() or "0.5",
            )
            click.echo(t["process_device_hint"])
            dev_def = os.getenv("SURVEY_DEVICE", "auto").strip() or "auto"
            device = _read_line(t["process_device"], dev_def).lower() or "auto"

            no_l2 = _read_bool(
                t["process_no_l2"],
                _env_bool("SURVEY_NO_L2", False),
                t["bool_invalid"],
            )
            force = _read_bool(
                t["process_force"],
                _env_bool("SURVEY_FORCE_PROCESS", False),
                t["bool_invalid"],
            )
            verbose = _read_bool(
                t["process_verbose"],
                _env_bool("SURVEY_VERBOSE", False),
                t["bool_invalid"],
            )
            args = [
                "process",
                "-i",
                str(inp),
                "-o",
                str(out),
                "-m",
                str(model),
                "--confidence",
                conf_s,
                "--tile-size",
                tile_s,
                "--overlap",
                overlap_s,
                "--cluster-eps",
                eps_s,
                "--device",
                device,
            ]
            if mission:
                args += ["--mission-name", mission]
            if no_l2:
                args.append("--no-l2")
            if force:
                args.append("--force")
            if verbose:
                args.append("-v")
            _invoke(cli_group, args, t)
            continue

        if choice == "3":
            out_def = os.getenv("SURVEY_OUTPUT_DIR", "").strip()
            out_raw = _read_line(t["list_output"], out_def or None)
            if not out_raw:
                click.echo(t["err_not_dir"].format(path="(empty)"))
                continue
            out = _expand_path(out_raw)
            if not out.is_dir():
                click.echo(t["err_not_dir"].format(path=out))
                continue
            _invoke(cli_group, ["list", "-o", str(out)], t)
            continue

        if choice == "4":
            env_default = resolve_api_base_url().strip()
            fallback_url = env_default or "http://127.0.0.1:8000"
            api = _read_line(t["ping_url"], fallback_url)
            to_def = os.getenv("SURVEY_PING_TIMEOUT", "15").strip() or "15"
            to_s = _read_line(t["ping_timeout"], to_def)
            args = ["ping", "--api-url", api, "--timeout", to_s]
            _invoke(cli_group, args, t)
            continue

        if choice == "5":
            out_def = os.getenv("SURVEY_OUTPUT_DIR", "").strip()
            out_raw = _read_line(t["sync_output"], out_def or None)
            if not out_raw:
                click.echo(t["err_not_dir"].format(path="(empty)"))
                continue
            out = _expand_path(out_raw)
            if not out.is_dir():
                click.echo(t["err_not_dir"].format(path=out))
                continue

            mid_env = os.getenv("SURVEY_LOCAL_MISSION_ID", "").strip()
            mid_s = _read_int_optional(
                t["sync_mission_id"],
                mid_env,
                t["int_invalid"],
            )
            dry_run = _read_bool(
                t["sync_dry_run"],
                _env_bool("SURVEY_SYNC_DRY_RUN", False),
                t["bool_invalid"],
            )

            args: list[str] = ["sync", "-o", str(out)]
            if mid_s:
                args += ["--local-mission-id", mid_s]
            if dry_run:
                args.append("--dry-run")
                args.append("--chunked")
            else:
                env_url = resolve_api_base_url().strip()
                api = _read_line(t["sync_api_url"], env_url or None)
                if not api:
                    click.echo(t["err_api_url_required"], err=True)
                    continue

                auth_mode = (_read_line(t["sync_auth_mode"], "2").strip() or "2")
                token = ""
                target_tid_s = ""

                if auth_mode == "2":
                    from getpass import getpass

                    from agri_guard_edge_survey.sync.center_auth import (
                        list_my_active_aerial_missions,
                        login_with_password,
                    )

                    lu = _read_line(
                        t["login_username"],
                        os.getenv("SURVEY_LOGIN_USERNAME", "").strip() or None,
                    )
                    if not lu:
                        click.echo(t["login_username_required"])
                        continue
                    pw = getpass(t["login_password_prompt"] + ": ")
                    try:
                        token = login_with_password(api, lu, pw)
                    except RuntimeError as exc:
                        click.echo(f"  {exc}", err=True)
                        continue
                    try:
                        missions = list_my_active_aerial_missions(api, token)
                    except RuntimeError as exc:
                        click.echo(f"  {exc}", err=True)
                        continue
                    if not missions:
                        click.echo(t["sync_no_active_missions"])
                        continue
                    click.echo(t["sync_pick_mission_header"])
                    for i, m in enumerate(missions, start=1):
                        click.echo(
                            f"  {i}) id={m.get('id')}  {m.get('name', '')!s}  [{m.get('status', '')}]"
                        )
                    pick_raw = _read_line(t["sync_pick_mission"], "")
                    if not pick_raw.isdigit():
                        click.echo(t["sync_pick_invalid"])
                        continue
                    pick_i = int(pick_raw)
                    if pick_i < 1 or pick_i > len(missions):
                        click.echo(t["sync_pick_invalid"])
                        continue
                    target_tid_s = str(missions[pick_i - 1]["id"])
                else:
                    env_tok = os.getenv("SURVEY_API_TOKEN", "").strip()
                    token = _read_line(t["sync_token"], env_tok or None)
                    if not token:
                        click.echo(t["err_sync_need_creds"])
                        continue
                    tid_env = os.getenv("SURVEY_TARGET_MISSION_ID", "").strip()
                    target_tid_s = _read_int_optional(
                        t["sync_target_cloud_mission"],
                        tid_env,
                        t["int_invalid"],
                    )

                args += ["--api-url", api, "--token", token]
                if target_tid_s.strip():
                    args += ["--target-mission-id", target_tid_s.strip()]

                force = _read_bool(
                    t["sync_force"],
                    _env_bool("SURVEY_SYNC_FORCE", False),
                    t["bool_invalid"],
                )
                resume = _read_bool(
                    t["sync_resume"],
                    _env_bool("SURVEY_SYNC_RESUME", False),
                    t["bool_invalid"],
                )
                retries_def = os.getenv("SURVEY_SYNC_RETRIES", "2").strip() or "2"
                retries_s = _read_line(t["sync_retries"], retries_def)
                args.append("--chunked")
                if force:
                    args.append("--force")
                if resume:
                    args.append("--resume")
                if retries_s.strip():
                    args += ["--retries", retries_s.strip()]

            verbose = _read_bool(
                t["sync_verbose"],
                _env_bool("SURVEY_VERBOSE", False),
                t["bool_invalid"],
            )
            if verbose:
                args.append("-v")
            _invoke(cli_group, args, t)
            continue

        click.echo(t["unknown_choice"])

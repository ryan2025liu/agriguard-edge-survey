# Edge Survey CLI — 使用说明（分发版）

---

## 1. 环境与依赖

| 项 | 说明 |
|----|------|
| Python | ≥ 3.10（与 `pyproject.toml` `requires-python` 一致） |
| 磁盘 | `process` 输出目录需容纳 SQLite、切片证据与小图预览 |
| GPU | 可选；无 GPU 时可用 CPU（速度明显下降） |
| 网络 | 仅 `survey sync`、`ping` 需要访问中心 HTTPS |

建议在虚拟环境中安装；**在项目仓库根目录**执行：

```bash
pip install -U pip setuptools wheel
pip install -e ./agri_guard_edge_survey
```

如遇 `torch` 与 CUDA 不匹配，请参考 PyTorch 官方说明先安装正确的 `torch` 套件，然后再执行上行。

---

## 2. 配置环境变量（同步与默认 API）

将 `.env` 放在常见工作目录（例如仓库根或你的 home 目录下每次启动前 `cd` 的位置）；`python-dotenv` 会加载。示例键名如下（详见包内 **`agri_guard_edge_survey/.env.example`** 若已随同步提供）：

- **`SURVEY_API_BASE_URL`**：中心 API 根地址（优先）
- **`AGRI_GUARD_API_BASE_URL`**：与前者二选一或与组织命名对齐时使用
- **`SURVEY_API_TOKEN`**：JWT（也可仅在命令行用 `--token` 传入）

**勿将含真实密钥的 `.env` 提交到 Git。**

---

## 3. 常用命令

### 设备与版本

```bash
survey info
survey --help
```

### 本地批量处理

```bash
survey process -i /path/to/DCIM -o ~/AgriGuard/run1 -m /path/to/model.pt
survey list -o ~/AgriGuard/run1
```

说明：`-i` 指向含 JPG/DNG 等格式的目录；`-m` 为 YOLO 权重。**首次跑前请用小目录试跑**。若输出目录已有 `results.db`，非 `--force` 可能拒绝覆盖（防止误删）。

### 联调与同步

```bash
survey ping --api-url https://your-api-host/
survey sync -o ~/AgriGuard/run1 --dry-run
survey sync -o ~/AgriGuard/run1 --api-url https://your-api-host/ --token "<JWT>"
```

大批量数据路径下通常使用 **分片同步**（`--chunked` / 续传等）；具体行为以当前 CLI `--help` 与贵司运维文档为准。

### 交互菜单（若构建启用）

不带子命令或 `survey menu` 可进入向导式菜单（语言与默认值见环境变量说明）。

---

## 4. 权限与帐号

云端导入接口通常要求帐号具备勘查/采集/管理等角色之一；使用与 Web 端一致的登录体系换取 JWT。无权时接口返回 **403**，需在中心侧为用户赋权而非在边缘侧绕过。

---

## 5. 常见问题

**Q：`pip install` 报找不到 `./agri_guard_core`**  

A：请先 `cd` 到包含 **`agri_guard_core` 与 `agri_guard_edge_survey` 并排**的本仓库根部再执行安装；或使用维护者文档中的两步显式安装。

**Q：投影 / GPS 全失败**

A：EXIF 中缺高度、焦距、云台朝向等会导致 `project_pixel_to_gps` 无法工作；确认相机与航拍器写入完整元数据。

**Q：`sync` 超时或 413**

A：网关/反向代理可能对请求体与时间有限制；万级影像应使用服务端支持的**分片导入**会话流，必要时联系中心运维调大超时与配额。

---

## 6. 进一步阅读

若有权访问上游设计文档：**Edge Survey AI CLI**（功能细节、会话状态文件、云端字段说明）请以贵司归档或 monorepo 内 `docs/02_architecture/edge_survey_ai_cli.md` 的同步副本为准。

# Edge Survey 分发版 — 架构说明

面向：技术负责人 / 集成方 / 需要从仓库理解「边缘侧与中心如何分界」的阅读者。

---

## 1. 仓库边界

本分发仓库**刻意只包含**两个 Python 包目录：

| 目录 | 角色 |
|------|------|
| `agri_guard_core` | 图像读入（含 EXIF）、大图切片、像素→GPS 投影、检测结果地理聚类等**与业务无关的算法内核** |
| `agri_guard_edge_survey` | `survey` CLI、本地 SQLite、`sync` / 分片上传客户端，与云端 **Edge Survey** HTTP API 交互 |

不包含：PostgreSQL / FastAPI / 前端。**中心侧必须以已部署的后端为前提**。

---

## 2. 安装与打包约定

边缘包依赖通过 **PEP 508** 指向同仓库根部的兄弟目录：

```text
agri-guard-core @ file:./agri_guard_core
```

因此：**`pip` 运行时当前工作目录**必须能看到 `./agri_guard_core`。推荐始终在**本仓库根部**执行 `pip install -e ./agri_guard_edge_survey`，不要仅拷贝 `agri_guard_edge_survey` 单目录到其他路径后盲装（除非你同时按文档改为显式两步安装或使用内部 PyPI/Git 坐标）。

---

## 3. 数据流（概要）

```
航拍原图目录 (本地)
       │
       ▼
 survey process ──► 切片 + YOLO (.pt)
       │
       ├── SQLite + 裁剪/预览（输出目录，不上传原图）
       │
       └── survey sync ──► HTTPS ──► 中心 POST /edge/survey/...
                            （JWT / 会话 / 分片等由 CLI 与服务端协定）
```

**安全约束摘要**：不向中心上传完整未裁剪原图的默认路径由产品设计保证；实际操作以 CLI 与后端版本说明为准。

---

## 4. 与云端 API 契约

CLI 假定中心提供（至少）Edge Survey 相关路由：`ping`、`import`、以及（可选）**分片**会话生命周期。服务端实现、错误码与包体大小限制**不在本分发仓库内**；集成前请在现场对目标环境做一次 `survey ping` 与 `sync --dry-run`。

---

## 5. Git 与外部分发角色的关系（维护者视图）

本分发仓库是 monorepo 的**可追溯快照**。维护流程与分支 / 版本策略见 monorepo 内 **`docs/05_guides/edge_survey_standalone_distribution.md`**；独立仓库内可将精简版拷贝到 **`docs/`** 或/wiki。

**终端用户**：只需 `git clone` 与上文安装步骤；一般不 fork 业务流程。

---

## 6. 扩展与定制

替换 `model.pt`、调整切片与聚类超参数由 CLI / `agri_guard_core` API 边界支持；若在边缘侧嵌入新依赖，请仍在**不破坏与中心 manifest 兼容性**的前提下进行，并保持 `pyproject.toml` 与子依赖许可证合规。

---

## 7. 许可证

本分发包源代码默认随仓库根 **`LICENSE`（MIT）** 分发；与本说明矛盾的以根目录 **`LICENSE`** 为准。运行时第三方库（YOLO/Torch/sklearn 等）遵循其各自许可证。

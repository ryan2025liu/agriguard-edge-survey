# AgriGuard Edge Survey CLI（分发版）

本地航测大图处理：**切片 → YOLO 推理 → GPS 聚合 → SQLite**；可选将结果同步到中心 **Edge Survey API**。原图保留在本地磁盘，按设计仅导出裁剪与小图。**本仓库不包含** AgriGuard Web / API 后端源码。

---

## 快速安装

**前置**：Python ≥ 3.10，建议预先创建虚拟环境。

**请务必在本仓库的根目录执行**（与 `pyproject.toml` 中 `file:./agri_guard_core` 路径约定一致）：

```bash
git clone https://github.com/ryan2025liu/agriguard-edge-survey.git
cd <repo-root>
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -U pip setuptools wheel
pip install -e ./agri_guard_edge_survey
survey --help
```

说明：本条命令会通过依赖自动安装并排目录下的 **`agri_guard_core`**。PyTorch / CUDA 需按你所用平台另行选择官方轮子（可先装 `torch` 再安装本仓库，或由 `pip` 一并解析）。

GPU / Apple Silicon 请参考 [PyTorch 官方安装文档](https://pytorch.org/get-started/locally/)。

---

## 典型用法摘要

```bash
survey info
survey process -i /path/to/DCIM -o ~/AgriGuard/run1 -m /path/to/model.pt
survey list -o ~/AgriGuard/run1
survey ping --api-url https://your-api-host/
survey sync -o ~/AgriGuard/run1 --api-url ... --token "<JWT>"
```

详细参数、`--dry-run`、分片同步、环境与排障：**见仓库内 [`docs/USAGE.md`](docs/USAGE.md)**。

架构、与云端接口边界、分发仓库维护方式：**见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**。

---

## 目录结构

```
.
├── agri_guard_core/         # AI 预处理与几何内核（与本 CLI 同属分发包）
├── agri_guard_edge_survey/  # CLI 与边缘流水线
├── docs/
├── LICENSE                  # MIT
├── README.md
└── UPSTREAM_REVISION.txt
```

---

## 版权声明与技术联系

- **单位**: J-INAN S&T COMPANY
- **作者**: Ryan.L
- **邮箱**: iuan.liu@gmail.com

## 许可证（MIT）

本仓库中与 Edge Survey CLI 一并分发的 **`agri_guard_core` / `agri_guard_edge_survey` 源代码**以 **[MIT License](LICENSE)** 提供（详见 `LICENSE` 首段copyright）。二进制或源码再分发时请保留版权声明与 **`LICENSE`** 全文。运行时依赖（PyTorch、Ultralytics、`scikit-learn` 等）遵循其自有许可证。

---

## 上游与变更说明

本分发内容与 **AgriGuard `media-ai` monorepo** 内对应目录应保持可追溯一致；请参考根目录 **`UPSTREAM_REVISION.txt`**（若维护者提供）与 **`RELEASE_NOTES.md`** 了解快照版本与兼容性。

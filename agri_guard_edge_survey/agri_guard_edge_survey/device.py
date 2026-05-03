"""
[INPUT]: User preference string (auto / cuda / mps / cpu).
[OUTPUT]: Ultralytics/YOLO `device` argument value.
[POS]: Cross-platform GPU/MPS/CPU selection for Edge Survey CLI.
[PROTOCOL]:
 1. `auto` prefers CUDA, then Apple MPS, then CPU.
 2. Do not import torch at top level if `auto` is unused — kept simple for CLI startup.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def resolve_device(preference: str) -> str:
    pref = (preference or "auto").strip().lower()
    if pref == "auto":
        return detect_device()
    if pref == "cuda":
        return "0"
    if pref in ("mps", "cpu"):
        return pref
    raise ValueError(f"Unknown device preference: {preference}")


def detect_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def get_runtime_info() -> Dict[str, Any]:
    import platform

    out: Dict[str, Any] = {
        "os": platform.system(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "device_auto": detect_device(),
        "torch": None,
        "cuda_available": None,
        "mps_available": None,
    }
    try:
        import torch

        out["torch"] = torch.__version__
        out["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            out["cuda_device"] = torch.cuda.get_device_name(0)
        out["mps_available"] = bool(
            hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        )
    except ImportError:
        out["torch"] = "(not installed)"

    return out


def format_info_lines(info: Optional[Dict[str, Any]] = None) -> str:
    i = info or get_runtime_info()
    lines = [
        "=" * 50,
        "AgriGuard Edge Survey AI",
        "=" * 50,
        f"OS:        {i['os']} ({i['arch']})",
        f"Python:    {i['python']}",
        f"PyTorch:   {i['torch']}",
    ]
    if i.get("cuda_available") is not None:
        lines.append(f"CUDA:      {i['cuda_available']}")
        if i.get("cuda_device"):
            lines.append(f"CUDA GPU:  {i['cuda_device']}")
    if i.get("mps_available") is not None:
        lines.append(f"MPS:       {i['mps_available']}")
    lines.append(f"device(auto): {i['device_auto']}")
    lines.append("=" * 50)
    return "\n".join(lines)

#!/usr/bin/env python3
"""检查 src/ 下业务模块是否导入了 logger.

排除项：
- __init__.py（通常只做 re-export）
- common/logger.py（logger 自身）
- common/config.py（纯配置，无业务逻辑）
- common/models.py（纯 ORM 模型定义）
- common/db.py（纯连接工厂）
- c3_push/channel.py（抽象接口）
"""

import sys
from pathlib import Path

_EXCLUDES = {
    "__init__.py",
    "logger.py",
    "config.py",
    "models.py",
    "db.py",
    "channel.py",         # 抽象接口
    "report_builder.py",  # 纯格式化，无外部调用
    "storage_state.py",   # 纯文件检查工具
}

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def check() -> list[str]:
    """返回缺少 logger 导入的文件列表."""
    missing: list[str] = []
    for py_file in sorted(_SRC_DIR.rglob("*.py")):
        if py_file.name in _EXCLUDES:
            continue
        text = py_file.read_text(encoding="utf-8")
        if "get_logger" not in text:
            missing.append(str(py_file.relative_to(_SRC_DIR.parent)))
    return missing


def main() -> int:
    missing = check()
    if not missing:
        print("logger check: all modules have logger import")
        return 0
    print(f"logger check FAILED: {len(missing)} module(s) missing get_logger import:")
    for path in missing:
        print(f"  - {path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

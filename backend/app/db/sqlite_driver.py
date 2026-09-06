"""为本项目固定受验证的 SQLite 运行时。"""

import sys
from dataclasses import dataclass

MIN_SQLITE_VERSION = (3, 51, 3)


@dataclass(frozen=True)
class SqliteRuntime:
    version: tuple[int, int, int]

    @property
    def version_text(self) -> str:
        return ".".join(map(str, self.version))


def ensure_sqlite_runtime() -> SqliteRuntime:
    """使后续 SQLAlchemy 导入使用受支持的 pysqlite3 驱动。

    不能让应用静默回退到 Python 自带 sqlite3：当前系统自带版本低于本项目
    WAL 基线。必须在任何 SQLAlchemy 导入前运行此函数。
    """
    try:
        import pysqlite3
    except ImportError as exc:  # pragma: no cover - 仅在环境安装错误时触发
        raise RuntimeError("缺少 pysqlite3；请先运行 scripts/build_sqlite_driver.sh") from exc

    version = tuple(pysqlite3.sqlite_version_info[:3])
    if version < MIN_SQLITE_VERSION:
        required = ".".join(map(str, MIN_SQLITE_VERSION))
        raise RuntimeError(
            f"SQLite 运行时为 {pysqlite3.sqlite_version}，低于项目要求的 {required}；"
            "请重新运行 scripts/build_sqlite_driver.sh"
        )

    sys.modules["sqlite3"] = pysqlite3
    return SqliteRuntime(version=version)

"""Alembic 环境。

首个实现迭代需引入全部 SQLAlchemy 模型并生成初始迁移；禁止以 create_all
替代迁移版本管理。
"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.base import Base
import app.models  # noqa: F401 - 注册迁移元数据

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

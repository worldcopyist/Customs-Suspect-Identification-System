from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有持久化实体的共同基类；具体表在后续迁移阶段加入。"""

"""Every test, including health checks, uses an isolated database and media root."""
import pytest
from sqlalchemy import create_engine,event
from app.core.config import get_settings
from app.db.session import SessionLocal
@pytest.fixture(autouse=True)
def isolated_system(tmp_path):
    settings=get_settings();old={k:getattr(settings,k) for k in ("database_url","media_root","logs_root")};bind=SessionLocal.kw["bind"]
    settings.database_url=f"sqlite:///{tmp_path/'test.db'}";settings.media_root=tmp_path/'media';settings.logs_root=tmp_path/'logs'
    engine=create_engine(settings.database_url,connect_args={"check_same_thread":False})
    @event.listens_for(engine,"connect")
    def pragmas(c,_):c.execute("PRAGMA foreign_keys=ON");c.execute("PRAGMA journal_mode=WAL")
    SessionLocal.configure(bind=engine)
    yield
    SessionLocal.configure(bind=bind);engine.dispose()
    for k,v in old.items():setattr(settings,k,v)

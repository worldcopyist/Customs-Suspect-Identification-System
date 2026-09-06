"""Consistent SQLite online backup. Never overwrite an existing destination."""
import argparse,os
from pathlib import Path
from app.db.sqlite_driver import ensure_sqlite_runtime
ensure_sqlite_runtime()
import sqlite3
from app.core.config import get_settings
def main():
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);args=p.parse_args()
    source=Path(get_settings().database_url.removeprefix('sqlite:///')).resolve()
    target=args.destination.resolve()
    if not source.is_file():raise SystemExit('Source database does not exist')
    if target==source or target.exists():raise SystemExit('Refusing to overwrite destination')
    target.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Backup integrity check failed')
    print('Verified database backup:',target)
if __name__=='__main__':main()

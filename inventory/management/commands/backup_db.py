"""
backup_db — VACUUM the live SQLite database, write a timestamped backup copy, and
drop backups older than N days.

SQLite only (dev + the PythonAnywhere free-tier deploy). Safe to run while the web app
is serving: VACUUM compacts the live file (reclaiming free pages so it stays small under
the 512 MB quota), then a consistent snapshot is written with SQLite's online-backup API.
Backups live on the same disk and count against the same quota, so old ones are pruned.

Schedule on PythonAnywhere (Tasks tab, once daily):
    cd /home/<user>/Anbar-Bot && \
      /home/<user>/.virtualenvs/<venv>/bin/python manage.py backup_db
"""
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# PythonAnywhere home dirs are lowercase and match the account name; adjust with --dest
# if the real path differs (e.g. /home/alirezaabavi).
DEFAULT_DEST = "/home/AlirezaAbavi"
DEFAULT_MAX_AGE_DAYS = 7
_MB = 1_048_576


class Command(BaseCommand):
    help = "VACUUM the SQLite DB, write a timestamped backup, and prune backups older than N days."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dest",
            default=DEFAULT_DEST,
            help="Directory to write backups into (default: %(default)s).",
        )
        parser.add_argument(
            "--max-age-days",
            type=int,
            default=DEFAULT_MAX_AGE_DAYS,
            help="Delete backups older than this many days (default: %(default)s).",
        )

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        if "sqlite" not in db["ENGINE"]:
            raise CommandError(
                f"backup_db supports SQLite only; configured engine is {db['ENGINE']}."
            )

        src = Path(db["NAME"])
        if not src.is_file():
            raise CommandError(f"Database file not found: {src}")

        dest_dir = Path(opts["dest"])
        dest_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        dest = dest_dir / f"{src.stem}-{stamp}.sqlite3"

        # 1) VACUUM the live DB. busy_timeout lets it wait out a transient lock from the
        #    web app rather than failing immediately.
        con = sqlite3.connect(str(src), timeout=30)
        try:
            con.execute("PRAGMA busy_timeout=30000")
            con.execute("VACUUM")
        finally:
            con.close()
        self.stdout.write(f"VACUUM done: {src} ({src.stat().st_size / _MB:.2f} MB)")

        # 2) Consistent online-backup snapshot into the destination.
        src_con = sqlite3.connect(str(src), timeout=30)
        dst_con = sqlite3.connect(str(dest))
        try:
            src_con.execute("PRAGMA busy_timeout=30000")
            with dst_con:
                src_con.backup(dst_con)
        finally:
            dst_con.close()
            src_con.close()
        self.stdout.write(
            self.style.SUCCESS(f"Backup written: {dest} ({dest.stat().st_size / _MB:.2f} MB)")
        )

        # 3) Prune backups older than --max-age-days.
        cutoff = time.time() - opts["max_age_days"] * 86400
        pruned = 0
        for old in dest_dir.glob(f"{src.stem}-*.sqlite3"):
            if old.stat().st_mtime < cutoff:
                old.unlink()
                pruned += 1
                self.stdout.write(f"Pruned (>{opts['max_age_days']}d old): {old.name}")
        self.stdout.write(f"Prune complete: {pruned} old backup(s) removed.")

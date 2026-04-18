# Copyright (C) 2026 Andrea Beggi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base, Setting, ScanStatus
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./proxlook.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def _migrate_legacy_schema():
    """Apply lightweight SQLite migrations for older local databases."""
    with engine.begin() as conn:
        table_rows = conn.execute(text("PRAGMA table_info(pve_hosts)")).fetchall()
        columns = {row[1] for row in table_rows}

        if "display_name" not in columns:
            conn.execute(text("ALTER TABLE pve_hosts ADD COLUMN display_name VARCHAR"))
        if "sort_order" not in columns:
            conn.execute(text("ALTER TABLE pve_hosts ADD COLUMN sort_order INTEGER DEFAULT 0"))

        # Backfill null values for safer ordering/serialization.
        conn.execute(text("UPDATE pve_hosts SET sort_order = 0 WHERE sort_order IS NULL"))

def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_legacy_schema()
    db = SessionLocal()
    # Initialize default settings
    if not db.query(Setting).filter(Setting.key == "scan_cron").first():
        db.add(Setting(key="scan_cron", value=""))
    if not db.query(ScanStatus).first():
        db.add(ScanStatus(id=1))
    db.commit()
    db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from database import SessionLocal
from models import Setting
from scanner import run_scan
import logging

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

def update_scheduler_job():
    db = SessionLocal()
    cron_setting = db.query(Setting).filter(Setting.key == "scan_cron").first()
    cron_expr = cron_setting.value if cron_setting else "*/5 * * * *"
    db.close()
    
    if scheduler.get_job('scan_job'):
        scheduler.remove_job('scan_job')
    
    scheduler.add_job(
        run_scan,
        CronTrigger.from_crontab(cron_expr),
        id='scan_job',
        max_instances=1,
        coalesce=True,
    )
    logger.info(f"Scan job updated with cron: {cron_expr}")

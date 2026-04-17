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

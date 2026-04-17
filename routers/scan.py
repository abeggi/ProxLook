from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import ScanStatus, Setting
from scanner import run_scan, is_scan_running
import asyncio
import datetime
import json

router = APIRouter(prefix="/api/scan")
SCAN_SUMMARY_SETTING_KEY = "last_scan_summary_json"

@router.post("")
async def trigger_scan():
    if is_scan_running():
        return {"status": "busy", "message": "A scan is already running"}

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_scan)
    return {"status": "started"}

@router.get("/status")
async def get_scan_status(db: Session = Depends(get_db)):
    status = db.query(ScanStatus).first()
    summary_setting = db.query(Setting).filter(Setting.key == SCAN_SUMMARY_SETTING_KEY).first()
    summary_payload = None
    if summary_setting and summary_setting.value:
        try:
            summary_payload = json.loads(summary_setting.value)
        except Exception:
            summary_payload = None
    if status and status.last_scan_time:
        # Ensure UTC timezone is attached before converting to ISO
        dt = status.last_scan_time
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return {
            "last_scan_time": dt.isoformat(),
            "last_scan_duration_seconds": status.last_scan_duration_seconds,
            "last_scan_status": status.last_scan_status,
            "last_scan_error": status.last_scan_error,
            "last_scan_summary": summary_payload,
        }
    return status

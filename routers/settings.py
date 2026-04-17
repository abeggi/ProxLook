from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Setting, PVEHost
from pydantic import BaseModel, Field
from typing import List, Optional
from scheduler_manager import update_scheduler_job
from apscheduler.triggers.cron import CronTrigger
from proxmoxer import ProxmoxAPI
import re

router = APIRouter(prefix="/api/settings")

class PVEHostSchema(BaseModel):
    id: Optional[int] = None
    display_name: Optional[str] = None
    host: str = Field(..., min_length=1)
    port: int = 8006
    user: str = Field(..., min_length=1)
    token_name: str = Field(..., min_length=1)
    token_value: str = Field(..., min_length=1)
    verify_ssl: bool = False
    sort_order: int = 0

class SettingsUpdate(BaseModel):
    pve_hosts: List[PVEHostSchema]
    scan_cron: str


HOST_RE = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9][a-zA-Z0-9\-]{0,62})(\.[a-zA-Z0-9][a-zA-Z0-9\-]{0,62})*$")
IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
TOKEN_NAME_RE = re.compile(r"^([^!\s]+![^!\s]+|[^!\s]+)$")


class HostConnectionTestRequest(BaseModel):
    id: Optional[int] = None
    host: str = Field(..., min_length=1)
    port: int = 8006
    user: str = Field(..., min_length=1)
    token_name: str = Field(..., min_length=1)
    token_value: Optional[str] = None
    verify_ssl: bool = False


def _is_valid_ipv4(value: str) -> bool:
    if not IPV4_RE.match(value):
        return False
    parts = value.split(".")
    return all(0 <= int(part) <= 255 for part in parts)


def _validate_host_config(host: str, port: int, user: str, token_name: str) -> None:
    host_value = (host or "").strip()
    user_value = (user or "").strip()
    token_name_value = (token_name or "").strip()

    if not host_value:
        raise HTTPException(status_code=400, detail="Host is required")
    if not (_is_valid_ipv4(host_value) or HOST_RE.match(host_value)):
        raise HTTPException(status_code=400, detail="Host must be a valid IPv4 or hostname")
    if not (1 <= int(port) <= 65535):
        raise HTTPException(status_code=400, detail="Port must be between 1 and 65535")
    if "@" not in user_value or user_value.startswith("@") or user_value.endswith("@"):
        raise HTTPException(status_code=400, detail="User must be in format user@realm (e.g. root@pam)")
    if not TOKEN_NAME_RE.match(token_name_value):
        raise HTTPException(status_code=400, detail="Token name must be non-empty and cannot contain spaces")


@router.get("")
async def get_settings(db: Session = Depends(get_db)):
    hosts = db.query(PVEHost).order_by(PVEHost.sort_order).all()
    # Mask tokens
    hosts_masked = []
    for h in hosts:
        hosts_masked.append({
            "id": h.id,
            "display_name": h.display_name,
            "host": h.host,
            "port": h.port,
            "user": h.user,
            "token_name": h.token_name,
            "token_value": "***",
            "verify_ssl": h.verify_ssl,
            "sort_order": h.sort_order
        })
    
    scan_cron = db.query(Setting).filter(Setting.key == "scan_cron").first()
    
    return {
        "pve_hosts": hosts_masked,
        "scan_cron": scan_cron.value if scan_cron else "*/5 * * * *"
    }

@router.put("")
async def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    try:
        CronTrigger.from_crontab(data.scan_cron)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cron expression. Use 5-field crontab format.")

    # Update scan_cron
    cron_setting = db.query(Setting).filter(Setting.key == "scan_cron").first()
    if cron_setting:
        cron_setting.value = data.scan_cron
    else:
        db.add(Setting(key="scan_cron", value=data.scan_cron))
        
    # Update PVE Hosts
    incoming_ids = [h.id for h in data.pve_hosts if h.id is not None]
    # Delete hosts not in the update list
    db.query(PVEHost).filter(~PVEHost.id.in_(incoming_ids)).delete(synchronize_session=False)
    
    for h_data in data.pve_hosts:
        _validate_host_config(h_data.host, h_data.port, h_data.user, h_data.token_name)
        if h_data.id:
            existing = db.query(PVEHost).filter(PVEHost.id == h_data.id).first()
            if existing:
                existing.display_name = h_data.display_name
                existing.host = h_data.host
                existing.port = h_data.port
                existing.user = h_data.user
                existing.token_name = h_data.token_name
                if h_data.token_value != "***":
                    existing.token_value = h_data.token_value
                existing.verify_ssl = h_data.verify_ssl
                existing.sort_order = h_data.sort_order
        else:
            new_host = PVEHost(
                display_name=h_data.display_name,
                host=h_data.host,
                port=h_data.port,
                user=h_data.user,
                token_name=h_data.token_name,
                token_value=h_data.token_value,
                verify_ssl=h_data.verify_ssl,
                sort_order=h_data.sort_order
            )
            db.add(new_host)
            
    db.commit()
    update_scheduler_job()
    return {"status": "ok"}


@router.post("/test-host")
async def test_host_connection(data: HostConnectionTestRequest, db: Session = Depends(get_db)):
    _validate_host_config(data.host, data.port, data.user, data.token_name)
    token_value = (data.token_value or "").strip()
    if data.id is not None and (not token_value or token_value == "***"):
        existing = db.query(PVEHost).filter(PVEHost.id == data.id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Host not found")
        token_value = existing.token_value

    if not token_value or token_value == "***":
        raise HTTPException(status_code=400, detail="Token value required for connection test")

    try:
        proxmox = ProxmoxAPI(
            data.host,
            port=data.port,
            user=data.user,
            token_name=data.token_name,
            token_value=token_value,
            verify_ssl=data.verify_ssl,
            timeout=8,
        )
        nodes = proxmox.nodes.get()
        return {"status": "ok", "message": f"Connection successful ({len(nodes)} node(s) detected)"}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Connection failed: {exc}")

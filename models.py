from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class PVEHost(Base):
    __tablename__ = "pve_hosts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    display_name = Column(String, nullable=True)
    host = Column(String, nullable=False)
    port = Column(Integer, default=8006)
    user = Column(String, nullable=False)
    token_name = Column(String, nullable=False)
    token_value = Column(String, nullable=False)
    verify_ssl = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)

class Resource(Base):
    __tablename__ = "resources"
    id = Column(Integer, primary_key=True, autoincrement=True)
    pve_host_id = Column(Integer, ForeignKey("pve_hosts.id"))
    pve_host = Column(String) # Hostname or IP of the PVE host
    node = Column(String)
    vmid = Column(Integer)
    name = Column(String)
    type = Column(String) # 'qemu' or 'lxc'
    status = Column(String)
    ip = Column(String, default="")
    cpus = Column(Integer)
    maxmem = Column(Integer)
    maxdisk = Column(Integer)
    last_seen = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))

class ScanStatus(Base):
    __tablename__ = "scan_status"
    id = Column(Integer, primary_key=True, default=1)
    last_scan_time = Column(DateTime)
    last_scan_duration_seconds = Column(Float)
    last_scan_status = Column(String) # 'ok' or 'error'
    last_scan_error = Column(String, nullable=True)

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String)

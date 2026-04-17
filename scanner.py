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

import datetime
import logging
import re
import threading
import json
from proxmoxer import ProxmoxAPI
from sqlalchemy.orm import Session
from models import PVEHost, Resource, ScanStatus, Setting
from database import SessionLocal

logger = logging.getLogger(__name__)
SCAN_LOCK = threading.Lock()

IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
SCAN_SUMMARY_SETTING_KEY = "last_scan_summary_json"

def _valid_ipv4(ip):
    if not ip or not isinstance(ip, str):
        return False
    ip = ip.strip()
    if not IPV4_RE.match(ip):
        return False
    parts = ip.split(".")
    return all(0 <= int(p) <= 255 for p in parts)

def _extract_ipv4_from_text(value):
    if not value:
        return None
    match = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", str(value))
    if not match:
        return None
    ip = match.group(1)
    return ip if _valid_ipv4(ip) else None

def is_scan_running():
    return SCAN_LOCK.locked()


def _resource_key(item):
    return (item["pve_host_id"], item["node"], item["type"], item["vmid"])


def _resource_label(item):
    name = item.get("name") or f"vmid:{item.get('vmid')}"
    host = item.get("pve_host") or f"host:{item.get('pve_host_id')}"
    node = item.get("node") or "node:?"
    rtype = (item.get("type") or "?").upper()
    status = item.get("status") or "unknown"
    return f"{host}/{node} {rtype} {name} ({status})"


def _resource_identity(item):
    return f"{item.get('pve_host_id')}|{item.get('node')}|{item.get('type')}|{item.get('vmid')}"


def _build_scan_summary(previous_resources, current_resources, removed_resources):
    prev_map = {_resource_key(r): r for r in previous_resources}
    curr_map = {_resource_key(r): r for r in current_resources}

    added_keys = [k for k in curr_map.keys() if k not in prev_map]
    status_changed = []
    renamed = []
    ip_changed = []
    cpu_changed = []
    ram_changed = []
    disk_changed = []

    for key in curr_map.keys():
        if key not in prev_map:
            continue
        prev_item = prev_map[key]
        curr_item = curr_map[key]
        prev_status = prev_item.get("status")
        curr_status = curr_item.get("status")
        if prev_status != curr_status:
            status_changed.append({
                "id": _resource_identity(curr_item),
                "resource": _resource_label(curr_item),
                "from": prev_status,
                "to": curr_status,
            })
        prev_name = (prev_item.get("name") or "").strip()
        curr_name = (curr_item.get("name") or "").strip()
        if prev_name != curr_name:
            renamed.append({
                "id": _resource_identity(curr_item),
                "resource": _resource_label(curr_item),
                "from": prev_name,
                "to": curr_name,
            })
        prev_ip = (prev_item.get("ip") or "").strip()
        curr_ip = (curr_item.get("ip") or "").strip()
        if prev_ip != curr_ip:
            ip_changed.append({
                "id": _resource_identity(curr_item),
                "resource": _resource_label(curr_item),
                "from": prev_ip or "—",
                "to": curr_ip or "—",
            })
        prev_cpus = int(prev_item.get("cpus") or 0)
        curr_cpus = int(curr_item.get("cpus") or 0)
        if prev_cpus != curr_cpus:
            cpu_changed.append({
                "id": _resource_identity(curr_item),
                "resource": _resource_label(curr_item),
                "from": prev_cpus,
                "to": curr_cpus,
            })
        prev_ram = int(prev_item.get("maxmem") or 0)
        curr_ram = int(curr_item.get("maxmem") or 0)
        if prev_ram != curr_ram:
            ram_changed.append({
                "id": _resource_identity(curr_item),
                "resource": _resource_label(curr_item),
                "from": prev_ram,
                "to": curr_ram,
            })
        prev_disk = int(prev_item.get("maxdisk") or 0)
        curr_disk = int(curr_item.get("maxdisk") or 0)
        if prev_disk != curr_disk:
            disk_changed.append({
                "id": _resource_identity(curr_item),
                "resource": _resource_label(curr_item),
                "from": prev_disk,
                "to": curr_disk,
            })

    started = [item for item in status_changed if item["from"] != "running" and item["to"] == "running"]
    stopped = [item for item in status_changed if item["from"] == "running" and item["to"] != "running"]

    changed_resource_ids = set()
    changed_resource_reasons = {}

    def _add_reason(resource_id, reason):
        if not resource_id:
            return
        changed_resource_reasons.setdefault(resource_id, set()).add(reason)

    for collection in (status_changed, renamed, ip_changed, cpu_changed, ram_changed, disk_changed):
        for item in collection:
            if item.get("id"):
                changed_resource_ids.add(item["id"])
    for item in status_changed:
        _add_reason(item.get("id"), "status")
    for item in renamed:
        _add_reason(item.get("id"), "name")
    for item in ip_changed:
        _add_reason(item.get("id"), "ip")
    for item in cpu_changed:
        _add_reason(item.get("id"), "cpu")
    for item in ram_changed:
        _add_reason(item.get("id"), "ram")
    for item in disk_changed:
        _add_reason(item.get("id"), "disk")

    return {
        "added_count": len(added_keys),
        "removed_count": len(removed_resources),
        "status_changed_count": len(status_changed),
        "started_count": len(started),
        "stopped_count": len(stopped),
        "renamed_count": len(renamed),
        "ip_changed_count": len(ip_changed),
        "cpu_changed_count": len(cpu_changed),
        "ram_changed_count": len(ram_changed),
        "disk_changed_count": len(disk_changed),
        "added": [_resource_label(curr_map[k]) for k in added_keys][:20],
        "removed": [_resource_label(r) for r in removed_resources][:20],
        "started": [f"{item['resource']} ({item['from']} -> {item['to']})" for item in started][:20],
        "stopped": [f"{item['resource']} ({item['from']} -> {item['to']})" for item in stopped][:20],
        "status_changed": [f"{item['resource']} ({item['from']} -> {item['to']})" for item in status_changed][:20],
        "renamed": [f"{item['resource']} ({item['from']} -> {item['to']})" for item in renamed][:20],
        "ip_changed": [f"{item['resource']} ({item['from']} -> {item['to']})" for item in ip_changed][:20],
        "cpu_changed": [f"{item['resource']} ({item['from']} -> {item['to']})" for item in cpu_changed][:20],
        "ram_changed": [f"{item['resource']} ({item['from']} -> {item['to']})" for item in ram_changed][:20],
        "disk_changed": [f"{item['resource']} ({item['from']} -> {item['to']})" for item in disk_changed][:20],
        "changed_resource_ids": sorted(changed_resource_ids),
        "changed_resource_reasons": {
            rid: sorted(list(reasons))
            for rid, reasons in changed_resource_reasons.items()
        },
    }

def get_vm_ip(proxmox, node, vmid, vm_type, runtime_data=None):
    """Try to get the IP address of a VM/LXC."""
    # 1. Try QEMU Guest Agent (for VMs)
    if vm_type == 'qemu':
        try:
            interfaces = proxmox.nodes(node).qemu(vmid).agent.network_get_interfaces.get()
            for iface in interfaces:
                for addr in iface.get('ip-addresses', []):
                    ip = addr.get('ip-address')
                    if addr.get('ip-address-type') == 'ipv4' and ip not in ('127.0.0.1', '0.0.0.0'):
                        if _valid_ipv4(ip):
                            return ip
        except Exception:
            pass

    # 2. For LXC, prefer IP already provided by Proxmox summary/runtime list.
    # This is what the Proxmox UI summary typically shows, even with DHCP config.
    if vm_type == 'lxc' and isinstance(runtime_data, dict):
        for key in ("ip", "ip-address", "primary_ip"):
            ip = _extract_ipv4_from_text(runtime_data.get(key))
            if ip and ip not in ("127.0.0.1", "0.0.0.0"):
                return ip

    # 3. Try runtime interfaces for LXC (real current IP when available).
    if vm_type == 'lxc':
        try:
            interfaces = proxmox.nodes(node).lxc(vmid).interfaces.get()
            for iface in (interfaces or []):
                if iface.get("name") == "lo":
                    continue
                # Proxmox may return inet as string ("192.168.1.10/24") or list.
                inet_value = iface.get("inet")
                if isinstance(inet_value, str):
                    ip = _extract_ipv4_from_text(inet_value)
                    if ip and ip not in ("127.0.0.1", "0.0.0.0"):
                        return ip
                elif isinstance(inet_value, list):
                    for addr in inet_value:
                        ip = _extract_ipv4_from_text(addr)
                        if ip and ip not in ("127.0.0.1", "0.0.0.0"):
                            return ip

                # Additional fallback from detailed ip-addresses structure.
                for addr in iface.get("ip-addresses", []):
                    ip = _extract_ipv4_from_text(addr.get("ip-address"))
                    ip_type = str(addr.get("ip-address-type", "")).lower()
                    if ip and ip_type in ("inet", "ipv4") and ip not in ("127.0.0.1", "0.0.0.0"):
                        return ip
        except Exception:
            pass

    # 4. Generic runtime status fallback (best-effort for both qemu/lxc).
    try:
        if vm_type == "qemu":
            status = proxmox.nodes(node).qemu(vmid).status.current.get()
        else:
            status = proxmox.nodes(node).lxc(vmid).status.current.get()

        for key in ("ip", "ip-address", "primary_ip"):
            ip = _extract_ipv4_from_text(status.get(key))
            if ip and ip not in ("127.0.0.1", "0.0.0.0"):
                return ip
    except Exception:
        pass

    # 5. Fallback: Parse net0 from config. Ignore placeholders like "dhcp".
    try:
        config = proxmox.nodes(node).qemu(vmid).config.get() if vm_type == 'qemu' else proxmox.nodes(node).lxc(vmid).config.get()
        net0 = config.get('net0', '')
        # net0 example: virtio=4E:A5:7B:8A:2F:3D,bridge=vmbr0,firewall=1,ip=192.168.1.10/24
        if 'ip=' in net0:
            ip_part = net0.split('ip=')[1].split(',')[0]
            ip_part = ip_part.split('/')[0].strip()
            if ip_part.lower() in ('dhcp', 'manual', 'auto'):
                return ""
            if _valid_ipv4(ip_part):
                return ip_part
    except Exception:
        pass

    return ""

def run_scan():
    if not SCAN_LOCK.acquire(blocking=False):
        logger.info("Scan skipped: another scan is already running.")
        return {"status": "busy"}

    db: Session = SessionLocal()
    # Use naive UTC to avoid comparison errors with SQLite stored dates
    start_time = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    status_entry = db.query(ScanStatus).first()
    
    try:
        hosts = db.query(PVEHost).all()
        all_resources = []
        reached_host_ids = set()
        
        for host_config in hosts:
            if not host_config.host:
                logger.warning(f"Skipping host with empty hostname (ID: {host_config.id})")
                continue
                
            logger.info(f"Scanning PVE host: {host_config.host}...")
            try:
                proxmox = ProxmoxAPI(
                    host_config.host,
                    port=host_config.port,
                    user=host_config.user,
                    token_name=host_config.token_name,
                    token_value=host_config.token_value,
                    verify_ssl=host_config.verify_ssl
                )
                
                nodes = proxmox.nodes.get()
                reached_host_ids.add(host_config.id)
                logger.info(f"Found {len(nodes)} nodes on host {host_config.host}")
                for node_info in nodes:
                    node_name = node_info['node']
                    
                    # QEMU VMs
                    vms = proxmox.nodes(node_name).qemu.get(full=1)
                    logger.info(f"  Node {node_name}: Found {len(vms)} VMs")
                    for vm in vms:
                        vmid = vm['vmid']
                        ip = get_vm_ip(proxmox, node_name, vmid, 'qemu', vm)
                        all_resources.append({
                            'pve_host_id': host_config.id,
                            'pve_host': host_config.host,
                            'node': node_name,
                            'vmid': vmid,
                            'name': vm.get('name', ''),
                            'type': 'qemu',
                            'status': vm.get('status', 'unknown'),
                            'ip': ip,
                            'cpus': vm.get('cpus', 0),
                            'maxmem': vm.get('maxmem', 0),
                            'maxdisk': vm.get('maxdisk', 0),
                            'last_seen': start_time
                        })
                        
                    # LXC Containers
                    lxcs = proxmox.nodes(node_name).lxc.get()
                    logger.info(f"  Node {node_name}: Found {len(lxcs)} LXCs")
                    for lxc in lxcs:
                        vmid = lxc['vmid']
                        ip = get_vm_ip(proxmox, node_name, vmid, 'lxc', lxc)
                        all_resources.append({
                            'pve_host_id': host_config.id,
                            'pve_host': host_config.host,
                            'node': node_name,
                            'vmid': vmid,
                            'name': lxc.get('name', ''),
                            'type': 'lxc',
                            'status': lxc.get('status', 'unknown'),
                            'ip': ip,
                            'cpus': lxc.get('cpus', 0),
                            'maxmem': lxc.get('maxmem', 0),
                            'maxdisk': lxc.get('maxdisk', 0),
                            'last_seen': start_time
                        })
                
                # Successful scan of this host: mark its resources as seen or update them
                # (handled below globally for simplicity and correctness as per instructions)
                
            except Exception as e:
                logger.error(f"Error scanning host {host_config.host}: {e}")
                # We don't delete resources if host is unreachable, they just won't have updated last_seen
                continue

        # Keep snapshot of previous resources for reached hosts, used for scan summary.
        previous_rows = db.query(Resource).filter(Resource.pve_host_id.in_(reached_host_ids)).all() if reached_host_ids else []
        previous_resources = [{
            "pve_host_id": row.pve_host_id,
            "pve_host": row.pve_host,
            "node": row.node,
            "type": row.type,
            "vmid": row.vmid,
            "name": row.name,
            "status": row.status,
            "ip": row.ip,
            "cpus": row.cpus,
            "maxmem": row.maxmem,
            "maxdisk": row.maxdisk,
        } for row in previous_rows]

        # Upsert resources
        for res_data in all_resources:
            existing = db.query(Resource).filter(
                Resource.vmid == res_data['vmid'],
                Resource.pve_host_id == res_data['pve_host_id']
            ).first()
            if existing:
                for key, value in res_data.items():
                    setattr(existing, key, value)
            else:
                db.add(Resource(**res_data))
        
        db.commit()
        
        # Cleanup: Delete resources not seen in this scan run (only for hosts that were successfully reached)
        # Actually, the requirement says: DELETE all resources where last_seen < scan start timestamp
        # and "If a PVE host is unreachable: do not delete its resources".
        # So we should only delete resources if their PVE host WAS successfully scanned in this run.
        removed_rows = []
        removed_resources_data = []
        if reached_host_ids:
            removed_rows = db.query(Resource).filter(
                Resource.last_seen < start_time,
                Resource.pve_host_id.in_(list(reached_host_ids))
            ).all()
            # Collect data BEFORE deleting
            for row in removed_rows:
                removed_resources_data.append({
                    "pve_host_id": row.pve_host_id,
                    "pve_host": row.pve_host,
                    "node": row.node,
                    "type": row.type,
                    "vmid": row.vmid,
                    "name": row.name,
                    "status": row.status,
                })
            db.query(Resource).filter(
                Resource.last_seen < start_time,
                Resource.pve_host_id.in_(list(reached_host_ids))
            ).delete(synchronize_session=False)
        
        db.commit()

        current_resources = [{
            "pve_host_id": item["pve_host_id"],
            "pve_host": item["pve_host"],
            "node": item["node"],
            "type": item["type"],
            "vmid": item["vmid"],
            "name": item["name"],
            "status": item["status"],
            "ip": item["ip"],
            "cpus": item["cpus"],
            "maxmem": item["maxmem"],
            "maxdisk": item["maxdisk"],
        } for item in all_resources]
        summary = _build_scan_summary(previous_resources, current_resources, removed_resources_data)
        
        duration = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - start_time).total_seconds()
        status_entry.last_scan_time = start_time
        status_entry.last_scan_duration_seconds = duration
        status_entry.last_scan_status = "ok"
        status_entry.last_scan_error = None
        summary_setting = db.query(Setting).filter(Setting.key == SCAN_SUMMARY_SETTING_KEY).first()
        summary_payload = {
            "scan_time": start_time.replace(tzinfo=datetime.timezone.utc).isoformat(),
            "summary": summary,
        }
        if summary_setting:
            summary_setting.value = json.dumps(summary_payload)
        else:
            db.add(Setting(key=SCAN_SUMMARY_SETTING_KEY, value=json.dumps(summary_payload)))
        db.commit()
        
    except Exception as e:
        logger.error(f"Global scan error: {e}")
        duration = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - start_time).total_seconds()
        status_entry.last_scan_time = start_time
        status_entry.last_scan_duration_seconds = duration
        status_entry.last_scan_status = "error"
        status_entry.last_scan_error = str(e)
        summary_setting = db.query(Setting).filter(Setting.key == SCAN_SUMMARY_SETTING_KEY).first()
        error_payload = {
            "scan_time": start_time.replace(tzinfo=datetime.timezone.utc).isoformat(),
            "summary": {
                "added_count": 0,
                "removed_count": 0,
                "status_changed_count": 0,
                "started_count": 0,
                "stopped_count": 0,
                "renamed_count": 0,
                "ip_changed_count": 0,
                "cpu_changed_count": 0,
                "ram_changed_count": 0,
                "disk_changed_count": 0,
                "added": [],
                "removed": [],
                "started": [],
                "stopped": [],
                "status_changed": [],
                "renamed": [],
                "ip_changed": [],
                "cpu_changed": [],
                "ram_changed": [],
                "disk_changed": [],
                "changed_resource_ids": [],
                "changed_resource_reasons": {},
                "error": str(e),
            },
        }
        if summary_setting:
            summary_setting.value = json.dumps(error_payload)
        else:
            db.add(Setting(key=SCAN_SUMMARY_SETTING_KEY, value=json.dumps(error_payload)))
        db.commit()
    finally:
        db.close()
        SCAN_LOCK.release()

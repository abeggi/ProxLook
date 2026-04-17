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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import Resource, PVEHost
import asyncio
import datetime
import time
from proxmoxer import ProxmoxAPI

router = APIRouter(prefix="/api")

def format_resource(res: Resource):
    # Ensure UTC timezone for JSON serialization
    dt = res.last_seen
    if dt and dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
        
    return {
        "id": res.id,
        "pve_host": res.pve_host,
        "pve_host_id": res.pve_host_id,
        "node": res.node,
        "vmid": res.vmid,
        "name": res.name,
        "type": res.type,
        "status": res.status,
        "ip": res.ip,
        "cpus": res.cpus,
        "maxmem": res.maxmem,
        "maxdisk": res.maxdisk,
        "last_seen": dt.isoformat() if dt else None
    }

@router.get("/inventory")
async def get_inventory(db: Session = Depends(get_db)):
    hosts = db.query(PVEHost).order_by(PVEHost.sort_order).all()
    inventory = {"pve_hosts": []}
    
    for host in hosts:
        host_data = {
            "host": host.host,
            "display_name": host.display_name,
            "id": host.id,
            "nodes": []
        }
        resources = db.query(Resource).filter(Resource.pve_host_id == host.id).all()
        
        # Group by node
        nodes_dict = {}
        for res in resources:
            if res.node not in nodes_dict:
                nodes_dict[res.node] = []
            nodes_dict[res.node].append(format_resource(res))
            
        for node_name, node_resources in nodes_dict.items():
            host_data["nodes"].append({
                "node": node_name,
                "resources": node_resources
            })
        
        inventory["pve_hosts"].append(host_data)
        
    return inventory

@router.get("/inventory/flat")
async def get_inventory_flat(db: Session = Depends(get_db)):
    resources = db.query(Resource).all()
    return [format_resource(r) for r in resources]

def get_vm_status(proxmox, node, vmid, vm_type):
    """Get current status of a VM/LXC"""
    try:
        if vm_type == "qemu":
            status_data = proxmox.nodes(node).qemu(vmid).status.current.get()
        else:  # lxc
            status_data = proxmox.nodes(node).lxc(vmid).status.current.get()
        return status_data.get("status", "unknown")
    except Exception as e:
        # Log the error but return unknown to continue waiting
        return "unknown"

def wait_for_status(proxmox, node, vmid, vm_type, target_status, timeout=60, check_interval=3):
    """
    Wait for VM/LXC to reach target status.
    Returns True if status reached, False if timeout.
    """
    start_time = time.time()
    last_status = "unknown"
    
    while time.time() - start_time < timeout:
        try:
            current_status = get_vm_status(proxmox, node, vmid, vm_type)
            
            # Track status changes for debugging
            if current_status != last_status:
                last_status = current_status
            
            if current_status == target_status:
                return True
                
            # If we're stopping and status is already stopped, return success
            if target_status == "stopped" and current_status in ["stopped", "unknown"]:
                return True
                
        except Exception as e:
            # If we get an error checking status, continue waiting
            pass
            
        time.sleep(check_interval)
    
    return False

@router.post("/resource/{pve_host_id}/{node}/{type}/{vmid}/{action}")
async def resource_action(pve_host_id: int, node: str, type: str, vmid: int, action: str, db: Session = Depends(get_db)):
    if action not in ["start", "stop"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    if type not in ["qemu", "lxc"]:
        raise HTTPException(status_code=400, detail="Invalid resource type")
        
    host_config = db.query(PVEHost).filter(PVEHost.id == pve_host_id).first()
    if not host_config:
        raise HTTPException(status_code=404, detail="Host not found")
    
    # Get the resource before the action to check if it exists
    resource = db.query(Resource).filter(
        Resource.pve_host_id == pve_host_id,
        Resource.node == node,
        Resource.type == type,
        Resource.vmid == vmid
    ).first()
    
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
        
    def do_action():
        # Create a new database session for the thread
        db_thread = SessionLocal()
        try:
            proxmox = ProxmoxAPI(
                host_config.host,
                port=host_config.port,
                user=host_config.user,
                token_name=host_config.token_name,
                token_value=host_config.token_value,
                verify_ssl=host_config.verify_ssl
            )
            
            # Execute the action
            if type == "qemu":
                if action == "start":
                    proxmox.nodes(node).qemu(vmid).status.start.post()
                    # Wait for VM to reach running state
                    if wait_for_status(proxmox, node, vmid, "qemu", "running"):
                        # Update database status
                        resource_thread = db_thread.query(Resource).filter(
                            Resource.pve_host_id == pve_host_id,
                            Resource.node == node,
                            Resource.type == type,
                            Resource.vmid == vmid
                        ).first()
                        if resource_thread:
                            resource_thread.status = "running"
                            resource_thread.last_seen = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                            db_thread.commit()
                    else:
                        raise Exception("VM failed to reach running state within timeout")
                else:
                    proxmox.nodes(node).qemu(vmid).status.stop.post()
                    # Wait for VM to reach stopped state
                    if wait_for_status(proxmox, node, vmid, "qemu", "stopped"):
                        # Update database status to stopped
                        resource_thread = db_thread.query(Resource).filter(
                            Resource.pve_host_id == pve_host_id,
                            Resource.node == node,
                            Resource.type == type,
                            Resource.vmid == vmid
                        ).first()
                        if resource_thread:
                            resource_thread.status = "stopped"
                            resource_thread.last_seen = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                            db_thread.commit()
                    else:
                        raise Exception("VM failed to reach stopped state within timeout")
            else:  # lxc
                if action == "start":
                    proxmox.nodes(node).lxc(vmid).status.start.post()
                    # Wait for LXC to reach running state
                    if wait_for_status(proxmox, node, vmid, "lxc", "running"):
                        # Update database status
                        resource_thread = db_thread.query(Resource).filter(
                            Resource.pve_host_id == pve_host_id,
                            Resource.node == node,
                            Resource.type == type,
                            Resource.vmid == vmid
                        ).first()
                        if resource_thread:
                            resource_thread.status = "running"
                            resource_thread.last_seen = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                            db_thread.commit()
                    else:
                        raise Exception("LXC failed to reach running state within timeout")
                else:
                    proxmox.nodes(node).lxc(vmid).status.stop.post()
                    # Wait for LXC to reach stopped state
                    if wait_for_status(proxmox, node, vmid, "lxc", "stopped"):
                        # Update database status to stopped
                        resource_thread = db_thread.query(Resource).filter(
                            Resource.pve_host_id == pve_host_id,
                            Resource.node == node,
                            Resource.type == type,
                            Resource.vmid == vmid
                        ).first()
                        if resource_thread:
                            resource_thread.status = "stopped"
                            resource_thread.last_seen = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                            db_thread.commit()
                    else:
                        raise Exception("LXC failed to reach stopped state within timeout")
            
            return {"status": "ok", "message": f"Resource {action} completed successfully"}
        except Exception as e:
            # Rollback any database changes on error
            db_thread.rollback()
            raise e
        finally:
            db_thread.close()

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, do_action)
        return result
    except Exception as e:
        error_msg = str(e)
        # Provide more user-friendly error messages
        if "timeout" in error_msg.lower() or "failed to reach" in error_msg.lower():
            error_msg = f"Resource did not reach '{action}' state within timeout period"
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": error_msg},
        )

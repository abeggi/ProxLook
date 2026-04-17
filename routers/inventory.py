from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Resource, PVEHost
import asyncio
import datetime
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

@router.post("/resource/{pve_host_id}/{node}/{type}/{vmid}/{action}")
async def resource_action(pve_host_id: int, node: str, type: str, vmid: int, action: str, db: Session = Depends(get_db)):
    if action not in ["start", "stop"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    if type not in ["qemu", "lxc"]:
        raise HTTPException(status_code=400, detail="Invalid resource type")
        
    host_config = db.query(PVEHost).filter(PVEHost.id == pve_host_id).first()
    if not host_config:
        raise HTTPException(status_code=404, detail="Host not found")
        
    def do_action():
        proxmox = ProxmoxAPI(
            host_config.host,
            port=host_config.port,
            user=host_config.user,
            token_name=host_config.token_name,
            token_value=host_config.token_value,
            verify_ssl=host_config.verify_ssl
        )
        if type == "qemu":
            if action == "start":
                proxmox.nodes(node).qemu(vmid).status.start.post()
            else:
                proxmox.nodes(node).qemu(vmid).status.stop.post()
        else:
            if action == "start":
                proxmox.nodes(node).lxc(vmid).status.start.post()
            else:
                proxmox.nodes(node).lxc(vmid).status.stop.post()
        return {"status": "ok"}

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, do_action)
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": str(e)},
        )

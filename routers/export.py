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

from fastapi import APIRouter, Depends
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Resource
import csv
import io
import json

router = APIRouter(prefix="/api/export")

@router.get("/csv")
async def export_csv(db: Session = Depends(get_db)):
    resources = db.query(Resource).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "PVE Host", "Node", "VMID", "Name", "Type", "Status", "IP", "CPUs", "Max RAM (GB)", "Max Disk (GB)", "Last Seen"])
    
    for r in resources:
        writer.writerow([
            r.id, r.pve_host, r.node, r.vmid, r.name, r.type, r.status, r.ip, r.cpus,
            round(r.maxmem / (1024**3), 2), round(r.maxdisk / (1024**3), 2),
            r.last_seen.isoformat() if r.last_seen else ""
        ])
        
    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=proxlook.csv"
    return response

@router.get("/json")
async def export_json(db: Session = Depends(get_db)):
    resources = db.query(Resource).all()
    data = []
    for r in resources:
        data.append({
            "id": r.id,
            "pve_host": r.pve_host,
            "node": r.node,
            "vmid": r.vmid,
            "name": r.name,
            "type": r.type,
            "status": r.status,
            "ip": r.ip,
            "cpus": r.cpus,
            "maxmem": r.maxmem,
            "maxdisk": r.maxdisk,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None
        })
    
    response = JSONResponse(content=data)
    response.headers["Content-Disposition"] = "attachment; filename=proxlook.json"
    return response

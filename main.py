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
import json
import asyncio
import logging
import paramiko
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from database import init_db, get_db
from scheduler_manager import scheduler, update_scheduler_job
from scanner import run_scan
from routers import inventory, scan, settings, export
from logging_setup import configure_logging

load_dotenv()

configure_logging()
logger = logging.getLogger(__name__)

# FastAPI App
app = FastAPI(title="ProxLook")

# Custom Static Files with No-Cache
class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# Mount static files
app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")

# Include Routers
app.include_router(inventory.router)
app.include_router(scan.router)
app.include_router(settings.router)
app.include_router(export.router)


@app.on_event("startup")
async def startup_event():
    init_db()
    update_scheduler_job()
    scheduler.start()
    # Trigger initial scan
    asyncio.get_event_loop().run_in_executor(None, run_scan)

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()

# Terminal and Home Routes
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/terminal.html")
async def read_terminal():
    return FileResponse(os.path.join(STATIC_DIR, "terminal.html"))

@app.get("/settings")
async def read_settings():
    return FileResponse(os.path.join(STATIC_DIR, "settings.html"))

# SSH WebSocket (as per instructions)
@app.websocket("/ws/ssh/{host}")
async def ws_ssh(websocket: WebSocket, host: str):
    await websocket.accept()

    # First message from client: JSON with credentials
    try:
        creds_raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
        creds = json.loads(creds_raw)
    except asyncio.TimeoutError:
        await websocket.close(); return
    except Exception:
        await websocket.close(); return

    username = creds.get("user", "")
    password = creds.get("password", "")
    port     = int(creds.get("port", 22))
    cols     = int(creds.get("cols", 80))
    rows     = int(creds.get("rows", 24))

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, port=port, username=username, password=password,
                    timeout=10, banner_timeout=15, auth_timeout=15)
    except paramiko.AuthenticationException:
        await websocket.send_bytes(b"\r\n\x1b[31mAuthentication failed.\x1b[0m\r\n")
        await websocket.send_text(json.dumps({"type": "close"}))
        await websocket.close(); return
    except Exception as e:
        await websocket.send_bytes(f"\r\n\x1b[31mConnection error: {e}\x1b[0m\r\n".encode())
        await websocket.send_text(json.dumps({"type": "close"}))
        await websocket.close(); return

    channel = ssh.invoke_shell(term="xterm-256color", width=cols, height=rows)
    channel.setblocking(False)

    async def ssh_reader():
        try:
            while True:
                await asyncio.sleep(0.02)
                if channel.recv_ready():
                    data = channel.recv(4096)
                    if not data: break
                    await websocket.send_bytes(data)
                if channel.exit_status_ready(): break
        except Exception: pass

    async def ws_reader():
        try:
            while True:
                msg = await websocket.receive()
                if "text" in msg:
                    try:
                        obj = json.loads(msg["text"])
                        if obj.get("type") == "resize":
                            channel.resize_pty(
                                width=obj.get("cols", 80), height=obj.get("rows", 24))
                        continue
                    except Exception: pass
                    channel.send(msg["text"].encode())
                elif "bytes" in msg:
                    channel.send(msg["bytes"])
        except WebSocketDisconnect: pass
        except Exception: pass

    reader_task = asyncio.create_task(ssh_reader())
    writer_task = asyncio.create_task(ws_reader())
    done, pending = await asyncio.wait(
        [reader_task, writer_task], return_when=asyncio.FIRST_COMPLETED)
    for t in pending: t.cancel()

    try: channel.close(); ssh.close()
    except Exception: pass

    try:
        await websocket.send_text(json.dumps({"type": "close"}))
        await asyncio.sleep(0.3)
        await websocket.close()
    except Exception: pass

# Run this if called directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("APP_PORT", 8090)))

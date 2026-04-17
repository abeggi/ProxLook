#!/bin/bash
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

# ProxLook - Systemd daemon management
# Manages ProxLook as a systemd service

set -e

APP_NAME="proxlook"
SERVICE_NAME="proxlook.service"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
APP_DIR="/inventory"

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then 
        echo "This command requires root privileges. Please run with sudo."
        exit 1
    fi
}

# Check if service is installed
is_installed() {
    if [ -f "$SERVICE_FILE" ]; then
        return 0
    else
        return 1
    fi
}

# Check if service is installed and show error if not
require_installed() {
    if ! is_installed; then
        echo "Error: ProxLook daemon is not installed."
        echo "Please install it first with: sudo ./manage.sh install"
        exit 1
    fi
}

install() {
    check_root
    
    if is_installed; then
        echo "ProxLook daemon is already installed."
        return 0
    fi
    
    echo "Installing ProxLook systemd daemon..."
    echo ""
    
    # Create systemd service file
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=ProxLook Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/main.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
SyslogIdentifier=proxlook

[Install]
WantedBy=multi-user.target
EOF
    
    echo "Created service file: $SERVICE_FILE"
    echo ""
    
    # Reload systemd
    systemctl daemon-reload
    echo "Reloaded systemd daemon."
    
    # Enable service to start on boot
    systemctl enable "$SERVICE_NAME"
    echo "Enabled service to start on boot."
    
    echo ""
    echo "✅ ProxLook daemon installed successfully!"
    echo ""
    echo "Next steps:"
    echo "  1. Start the service: sudo ./manage.sh start"
    echo "  2. Check status: sudo ./manage.sh status"
    echo "  3. View logs: sudo ./manage.sh logs"
    echo ""
    echo "Note: The service is configured to run as root to access"
    echo "      Proxmox API with appropriate permissions."
}

uninstall() {
    check_root
    require_installed
    
    echo "Uninstalling ProxLook systemd daemon..."
    echo ""
    
    # Stop service if running
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "Stopping service..."
        systemctl stop "$SERVICE_NAME"
    fi
    
    # Disable service
    if systemctl is-enabled --quiet "$SERVICE_NAME"; then
        echo "Disabling service..."
        systemctl disable "$SERVICE_NAME"
    fi
    
    # Remove service file
    echo "Removing service file..."
    rm -f "$SERVICE_FILE"
    
    # Reload systemd
    systemctl daemon-reload
    echo "Reloaded systemd daemon."
    
    echo ""
    echo "✅ ProxLook daemon uninstalled successfully!"
    echo ""
    echo "Note: Application data and database are preserved in:"
    echo "      $APP_DIR"
}

start() {
    check_root
    require_installed
    
    echo "Starting ProxLook daemon..."
    systemctl start "$SERVICE_NAME"
    
    # Wait a moment and check status
    sleep 1
    status
}

stop() {
    check_root
    require_installed
    
    echo "Stopping ProxLook daemon..."
    systemctl stop "$SERVICE_NAME"
    
    # Wait a moment and check status
    sleep 1
    status
}

restart() {
    check_root
    require_installed
    
    echo "Restarting ProxLook daemon..."
    systemctl restart "$SERVICE_NAME"
    
    # Wait a moment and check status
    sleep 1
    status
}

status() {
    check_root
    
    if ! is_installed; then
        echo "Status: Not installed"
        echo "Use: sudo ./manage.sh install"
        return 0
    fi
    
    echo "Service status:"
    systemctl status "$SERVICE_NAME" --no-pager --lines=0
}

logs() {
    check_root
    
    if ! is_installed; then
        echo "Error: ProxLook daemon is not installed."
        echo "Please install it first with: sudo ./manage.sh install"
        exit 1
    fi
    
    echo "Showing logs for ProxLook daemon (Ctrl+C to exit)..."
    echo ""
    journalctl -u "$SERVICE_NAME" -f
}

enable() {
    check_root
    require_installed
    
    echo "Enabling ProxLook daemon to start on boot..."
    systemctl enable "$SERVICE_NAME"
    echo "✅ Service enabled."
}

disable() {
    check_root
    require_installed
    
    echo "Disabling ProxLook daemon from starting on boot..."
    systemctl disable "$SERVICE_NAME"
    echo "✅ Service disabled."
}

case "$1" in
    install)
        install
        ;;
    uninstall)
        uninstall
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    enable)
        enable
        ;;
    disable)
        disable
        ;;
    *)
        echo "Usage: sudo ./manage.sh {install|uninstall|start|stop|restart|status|logs|enable|disable}"
        echo ""
        echo "ProxLook Systemd Daemon Management"
        echo "All commands require root privileges (use sudo)."
        echo ""
        echo "Commands:"
        echo "  install     Install ProxLook as a systemd daemon"
        echo "  uninstall   Uninstall ProxLook systemd daemon (preserves data)"
        echo "  start       Start the daemon"
        echo "  stop        Stop the daemon"
        echo "  restart     Restart the daemon"
        echo "  status      Show daemon status"
        echo "  logs        View daemon logs in real-time"
        echo "  enable      Enable daemon to start on boot"
        echo "  disable     Disable daemon from starting on boot"
        echo ""
        echo "For direct application run (without daemon), use: ./run.sh"
        echo ""
        exit 1
esac
#!/bin/bash
# ProxLook - Direct application runner (without daemon)
# Use for development or testing

set -e

APP_NAME="proxlook"
LOG_FILE="app.log"
PYTHON_BIN="python3"
MAIN_FILE="main.py"
PID_FILE="app.pid"

# Function to find the PID of the running application
get_pid() {
    # Try to get PID from file first
    if [ -f $PID_FILE ]; then
        PID=$(cat $PID_FILE)
        if ps -p $PID > /dev/null; then
            # Verify it's actually our python app
            if ps -fp $PID | grep -q "$MAIN_FILE"; then
                echo $PID
                return
            fi
        fi
    fi

    # Fallback: search process list for the main file
    PID=$(ps -ef | grep "$PYTHON_BIN $MAIN_FILE" | grep -v grep | awk '{print $2}')
    if [ ! -z "$PID" ]; then
        echo $PID
        echo $PID > $PID_FILE
    fi
}

start() {
    PID=$(get_pid)
    if [ ! -z "$PID" ]; then
        echo "$APP_NAME is already running (PID: $PID)"
        exit 0
    fi
    
    echo "Starting $APP_NAME directly (not as daemon)..."
    echo "Press Ctrl+C to stop"
    echo ""
    echo "Logs will be written to: $LOG_FILE"
    echo "You can also view logs in another terminal with: tail -f $LOG_FILE"
    echo ""
    
    # Start the application
    $PYTHON_BIN $MAIN_FILE
}

stop() {
    PID=$(get_pid)
    if [ ! -z "$PID" ]; then
        echo "Stopping $APP_NAME (PID: $PID)..."
        kill $PID
        # Wait for it to die
        for i in {1..5}; do
            if ! ps -p $PID > /dev/null; then
                break
            fi
            sleep 1
        done
        if ps -p $PID > /dev/null; then
            echo "Forcing stop..."
            kill -9 $PID
        fi
        rm -f $PID_FILE
        echo "$APP_NAME stopped."
    else
        echo "$APP_NAME is not running."
        rm -f $PID_FILE # Cleanup any stale file
    fi
}

status() {
    PID=$(get_pid)
    if [ ! -z "$PID" ]; then
        echo "$APP_NAME is running (PID: $PID)"
    else
        echo "$APP_NAME is not running."
    fi
}

logs() {
    if [ -f $LOG_FILE ]; then
        tail -f $LOG_FILE
    else
        echo "Log file $LOG_FILE not found."
    fi
}

restart() {
    stop
    sleep 2
    start
}

case "$1" in
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
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Direct application runner (without systemd daemon)"
        echo "Use for development or testing only."
        echo ""
        echo "Commands:"
        echo "  start     Start ProxLook directly (foreground)"
        echo "  stop      Stop ProxLook if running"
        echo "  restart   Restart ProxLook"
        echo "  status    Check if ProxLook is running"
        echo "  logs      View application logs in real-time"
        echo ""
        echo "For production daemon management, use: ./manage.sh"
        exit 1
esac
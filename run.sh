#!/bin/bash

# Mnemo C2 Bot Startup Script
# Usage: ./run.sh [start|stop|restart|status|logs]

BOT_DIR="/opt/mnemo"
BOT_SCRIPT="bot.py"
LOG_FILE="/var/log/mnemo/bot.log"
PID_FILE="/var/run/mnemo-bot.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if bot is running
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Function to start bot
start_bot() {
    if is_running; then
        echo -e "${YELLOW}⚠️  Bot is already running (PID: $(cat $PID_FILE))${NC}"
        return
    fi
    
    echo -e "${YELLOW}🚀 Starting Mnemo C2 Bot...${NC}"
    
    # Create log file if it doesn't exist
    touch "$LOG_FILE"
    
    # Start bot in background
    cd "$BOT_DIR"
    if [ -x "$BOT_DIR/venv/bin/python" ]; then
        "$BOT_DIR/venv/bin/python" "$BOT_SCRIPT" >> "$LOG_FILE" 2>&1 &
    else
        python3 "$BOT_SCRIPT" >> "$LOG_FILE" 2>&1 &
    fi
    
    # Save PID
    echo $! > "$PID_FILE"
    
    echo -e "${GREEN}✅ Bot started successfully (PID: $!)${NC}"
    echo -e "${GREEN}📝 Logs: $LOG_FILE${NC}"
}

# Function to stop bot
stop_bot() {
    if ! is_running; then
        echo -e "${YELLOW}⚠️  Bot is not running${NC}"
        return
    fi
    
    PID=$(cat "$PID_FILE")
    echo -e "${YELLOW}🛑 Stopping bot (PID: $PID)...${NC}"
    
    kill "$PID" 2>/dev/null
    sleep 2
    
    if is_running; then
        echo -e "${RED}⚠️  Bot didn't stop gracefully, sending SIGTERM again...${NC}"
        kill "$PID" 2>/dev/null
    fi
    
    rm -f "$PID_FILE"
    echo -e "${GREEN}✅ Bot stopped${NC}"
}

# Function to restart bot
restart_bot() {
    echo -e "${YELLOW}🔄 Restarting bot...${NC}"
    stop_bot
    sleep 2
    start_bot
}

# Function to show status
show_status() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        echo -e "${GREEN}✅ Bot is running (PID: $PID)${NC}"
        echo ""
        ps aux | grep "$PID" | grep -v grep
    else
        echo -e "${RED}❌ Bot is not running${NC}"
    fi
}

# Function to show logs
show_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo -e "${RED}❌ Log file not found: $LOG_FILE${NC}"
        return
    fi
    
    echo -e "${YELLOW}📖 Last 50 lines of logs (use Ctrl+C to exit):${NC}"
    tail -f "$LOG_FILE"
}

# Main logic
case "${1:-status}" in
    start)
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        restart_bot
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    *)
        echo "Mnemo C2 Bot Control Script"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the bot"
        echo "  stop    - Stop the bot"
        echo "  restart - Restart the bot"
        echo "  status  - Show bot status"
        echo "  logs    - Show live logs"
        echo ""
        exit 1
        ;;
esac

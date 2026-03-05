#!/bin/bash
# Start both the trading bot and dashboard in the same container
# so they share the same SQLite volume.

set -e

mkdir -p /app/data

echo "Starting trading bot..."
python scripts/run_bot.py &
BOT_PID=$!

echo "Starting dashboard..."
streamlit run dashboard/app.py \
    --server.address=0.0.0.0 \
    --server.port=8501 \
    --server.headless=true &
DASH_PID=$!

# If either process dies, kill the other and exit
wait -n $BOT_PID $DASH_PID
echo "A process exited. Shutting down..."
kill $BOT_PID $DASH_PID 2>/dev/null
exit 1

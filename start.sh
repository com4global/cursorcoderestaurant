#!/bin/bash
# Start backend and frontend for RestaurantAI
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Kill anything on our ports first
for port in 8000 5173; do
  pid=$(lsof -ti:$port 2>/dev/null) && kill -9 $pid 2>/dev/null && echo "Freed port $port" || true
done
sleep 1

echo "Starting backend on http://127.0.0.1:8000 ..."
(cd "$ROOT/backend" && python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:5173 ..."
(cd "$ROOT/frontend" && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "Backend PID: $BACKEND_PID  (http://127.0.0.1:8000)"
echo "Frontend PID: $FRONTEND_PID (http://localhost:5173)"
echo "Press Ctrl+C to stop both."
wait

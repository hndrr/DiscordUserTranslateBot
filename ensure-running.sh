#!/bin/bash
# Idempotent: start the Discord bot if it is not already running.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if pgrep -f 'tsx src/index\.ts' >/dev/null 2>&1; then
  echo "ALREADY_RUNNING"
  exit 0
fi

if [ ! -f .env ]; then
  echo "MISSING_ENV"
  exit 1
fi

if [ ! -d node_modules ]; then
  echo "INSTALLING"
  npm install
fi

mkdir -p logs
nohup bash run-forever.sh >> logs/bot.out 2>&1 &
disown || true

# Wait for ready (or give up)
for i in 1 2 3 4 5 6 7 8 9 10; do
  sleep 2
  if pgrep -f 'tsx src/index\.ts' >/dev/null 2>&1; then
    if tail -n 30 logs/bot.out | grep -q 'Bot is ready'; then
      echo "STARTED"
      exit 0
    fi
  fi
done

if pgrep -f 'tsx src/index\.ts' >/dev/null 2>&1; then
  echo "STARTED_PROCESS_ONLY"
  exit 0
fi

echo "START_FAILED"
exit 1

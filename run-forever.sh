#!/bin/bash
# Foreground crash-restart supervisor. Host shutdown still stops the bot.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f .env ] && [ -z "${DISCORD_TOKEN:-}" ]; then
    echo "Missing configuration: copy .env.example to .env, or provide environment variables."
    exit 1
fi
if [ ! -d node_modules ]; then
    echo "Missing dependencies: run npm ci before starting."
    exit 1
fi

# On Linux, prevent two launchers from answering the same interaction.
mkdir -p logs
if command -v flock >/dev/null 2>&1; then
    exec 8>>logs/bot.lock
    flock -n 8 || { echo "Bot supervisor is already running."; exit 1; }
fi

# Registration changes remote Discord state. Make it an explicit one-time step.
if [ "${DEPLOY_COMMANDS:-0}" = "1" ]; then
    npm run deploy
fi

child=""
stopping=0
stop() {
    stopping=1
    # Repeated stop signals must not restart or interrupt the shutdown deadline.
    trap '' INT TERM
    if [ -n "$child" ]; then
        kill -TERM "$child" 2>/dev/null || true
        for _ in {1..15}; do
            if ! kill -0 "$child" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        if kill -0 "$child" 2>/dev/null; then
            echo "Bot did not stop within 15 seconds; forcing shutdown."
            kill -KILL "$child" 2>/dev/null || true
        fi
        wait "$child" 2>/dev/null || true
    fi
    exit 0
}
trap stop INT TERM

echo "Starting bot supervisor (host must remain running)."
while [ "$stopping" -eq 0 ]; do
    node --import tsx src/index.ts &
    child=$!
    wait "$child" || true
    child=""
    echo "Bot stopped. Restarting in 5 seconds..."
    sleep 5 &
    child=$!
    wait "$child" || true
    child=""
done

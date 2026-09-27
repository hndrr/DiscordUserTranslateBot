#!/bin/bash
# Idempotent: ensure Node >= 22.13, then start the Discord bot if it is not already running.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REQUIRED_NODE_MAJOR=22
REQUIRED_NODE_MINOR=13
# Pin a known-good Node 22 build (matches what we verified on the Grok Bot computer).
NODE_DIST_VERSION="22.23.3"

node_meets_requirement() {
  command -v node >/dev/null 2>&1 || return 1
  node -e "
    const [maj, min] = process.versions.node.split('.').map(Number);
    process.exit(maj > ${REQUIRED_NODE_MAJOR} || (maj === ${REQUIRED_NODE_MAJOR} && min >= ${REQUIRED_NODE_MINOR}) ? 0 : 1);
  " 2>/dev/null
}

install_node_22() {
  echo "INSTALLING_NODE_${NODE_DIST_VERSION}"
  local arch tar_name url tmp
  case "$(uname -m)" in
    x86_64|amd64) arch="x64" ;;
    aarch64|arm64) arch="arm64" ;;
    *)
      echo "UNSUPPORTED_ARCH:$(uname -m)"
      return 1
      ;;
  esac
  tar_name="node-v${NODE_DIST_VERSION}-linux-${arch}.tar.xz"
  url="https://nodejs.org/dist/v${NODE_DIST_VERSION}/${tar_name}"
  tmp="$(mktemp -d)"
  curl -fsSL "$url" -o "${tmp}/${tar_name}"
  if command -v sudo >/dev/null 2>&1; then
    sudo tar -xJf "${tmp}/${tar_name}" -C /usr/local --strip-components=1
  else
    mkdir -p "$HOME/.local"
    tar -xJf "${tmp}/${tar_name}" -C "$HOME/.local" --strip-components=1
    export PATH="$HOME/.local/bin:$PATH"
  fi
  rm -rf "$tmp"
  hash -r 2>/dev/null || true
  if ! node_meets_requirement; then
    echo "NODE_INSTALL_FAILED:$(node -v 2>/dev/null || echo none)"
    return 1
  fi
  echo "NODE_READY:$(node -v)"
}

ensure_node() {
  if node_meets_requirement; then
    return 0
  fi
  install_node_22
}

# If an old bot is running under Node < 22.13, stop it so we can restart cleanly.
if pgrep -f 'tsx src/index\.ts' >/dev/null 2>&1; then
  if node_meets_requirement; then
    echo "ALREADY_RUNNING"
    exit 0
  fi
  echo "STOPPING_OLD_NODE_BOT"
  pkill -f 'run-forever\.sh' 2>/dev/null || true
  pkill -f 'tsx src/index\.ts' 2>/dev/null || true
  sleep 2
fi

ensure_node

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

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  sleep 2
  if pgrep -f 'tsx src/index\.ts' >/dev/null 2>&1; then
    if tail -n 40 logs/bot.out | grep -q 'Bot is ready'; then
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

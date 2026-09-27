#!/bin/bash
# Idempotent: ensure Node >= 22.13, then start the Discord bot if it is not already running.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

REQUIRED_NODE_MAJOR=22
REQUIRED_NODE_MINOR=13
# Pin a known-good Node 22 build (matches what we verified on the Grok Bot computer).
NODE_DIST_VERSION="22.23.3"
FOREVER_PID=""

node_bin_meets_requirement() {
  local node_bin="${1:-}"
  [ -n "$node_bin" ] && [ -x "$node_bin" ] || return 1
  "$node_bin" -e "
    const [maj, min] = process.versions.node.split('.').map(Number);
    process.exit(maj > ${REQUIRED_NODE_MAJOR} || (maj === ${REQUIRED_NODE_MAJOR} && min >= ${REQUIRED_NODE_MINOR}) ? 0 : 1);
  " 2>/dev/null
}

node_meets_requirement() {
  local node_bin
  node_bin="$(command -v node 2>/dev/null || true)"
  node_bin_meets_requirement "$node_bin"
}

cmdline_mentions_repo() {
  local cmdline="${1:-}"
  [[ "$cmdline" == *"$REPO_DIR/"* || "$cmdline" == *"$REPO_DIR "* || "$cmdline" == *"$REPO_DIR" ]]
}

is_repo_process() {
  local pid="${1:-}"
  local cwd cmdline
  [ -n "$pid" ] && [ -d "/proc/$pid" ] || return 1
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  if [[ "$cwd" == "$REPO_DIR" || "$cwd" == "$REPO_DIR"/* ]]; then
    return 0
  fi
  cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  cmdline_mentions_repo "$cmdline"
}

find_repo_pids() {
  local needle="${1:-}"
  local proc pid cmdline
  [ -n "$needle" ] || return 0
  for proc in /proc/[0-9]*; do
    pid="${proc#/proc/}"
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    case "$cmdline" in
      *"$needle"*) ;;
      *) continue ;;
    esac
    if is_repo_process "$pid"; then
      printf '%s\n' "$pid"
    fi
  done
}

bot_pids() { find_repo_pids 'tsx src/index.ts'; }
forever_pids() { find_repo_pids 'run-forever.sh'; }

has_repo_bot() {
  local pids
  pids="$(bot_pids || true)"
  [ -n "$pids" ]
}

resolve_node_bin_for_pid() {
  local pid="${1:-}" exe ppid
  local i
  for i in 1 2 3 4 5 6 7 8; do
    [ -n "$pid" ] && [ -d "/proc/$pid" ] || return 1
    exe="$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
    if [ -n "$exe" ] && [ -x "$exe" ] && "$exe" -p 'process.versions.node' >/dev/null 2>&1; then
      printf '%s\n' "$exe"
      return 0
    fi
    ppid="$(awk '/^PPid:/{print $2}' "/proc/$pid/status" 2>/dev/null || true)"
    [ -n "$ppid" ] && [ "$ppid" != 0 ] && [ "$ppid" != "$pid" ] || return 1
    pid="$ppid"
  done
  return 1
}

running_bot_node_meets() {
  local pid node_bin
  while read -r pid; do
    [ -n "$pid" ] || continue
    node_bin="$(resolve_node_bin_for_pid "$pid" || true)"
    if node_bin_meets_requirement "$node_bin"; then
      return 0
    fi
  done < <(bot_pids)
  return 1
}

stop_repo_bot() {
  local pid
  while read -r pid; do
    [ -n "$pid" ] || continue
    kill "$pid" 2>/dev/null || true
  done < <(forever_pids; bot_pids)
  sleep 2
  while read -r pid; do
    [ -n "$pid" ] || continue
    kill -9 "$pid" 2>/dev/null || true
  done < <(forever_pids; bot_pids)
}

kill_start_orphans() {
  if [ -n "${FOREVER_PID:-}" ] && kill -0 "$FOREVER_PID" 2>/dev/null; then
    kill "$FOREVER_PID" 2>/dev/null || true
  fi
  stop_repo_bot
}

can_install_usr_local() {
  if [ "$(id -u)" -eq 0 ]; then
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    return 0
  fi
  return 1
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
  if can_install_usr_local; then
    if [ "$(id -u)" -eq 0 ]; then
      tar -xJf "${tmp}/${tar_name}" -C /usr/local --strip-components=1
    else
      sudo -n tar -xJf "${tmp}/${tar_name}" -C /usr/local --strip-components=1
    fi
    export PATH="/usr/local/bin:$PATH"
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

mkdir -p logs
exec 9>>logs/ensure-running.lock
flock 9

# Re-check under the lock so concurrent callers serialize.
if has_repo_bot; then
  if running_bot_node_meets; then
    echo "ALREADY_RUNNING"
    exit 0
  fi
  echo "STOPPING_OLD_NODE_BOT"
  stop_repo_bot
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

nohup bash run-forever.sh >> logs/bot.out 2>&1 &
FOREVER_PID=$!
disown || true

for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  sleep 2
  if has_repo_bot; then
    if tail -n 40 logs/bot.out | grep -q 'Bot is ready'; then
      echo "STARTED"
      exit 0
    fi
  fi
done

if has_repo_bot; then
  echo "STARTED_PROCESS_ONLY"
  exit 0
fi

kill_start_orphans
echo "START_FAILED"
exit 1

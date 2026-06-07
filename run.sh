#!/usr/bin/env bash
# 仅支持 restart 的极简脚本

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PID_FILE="$ROOT/run/aigc-api.pid"
LOG_FILE="$ROOT/logs/aigc-api.log"

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"

# 自动选择 Python 解释器
pick_python() {
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    echo "$ROOT/.venv/bin/python"
    return
  fi
  if [[ -x "/opt/miniconda3/envs/aigc/bin/python" ]]; then
    echo "/opt/miniconda3/envs/aigc/bin/python"
    return
  fi
  if command -v python3.11 &>/dev/null; then
    command -v python3.11
    return
  fi
  command -v python3
}

PYTHON_BIN="$(pick_python)"

# 判断进程是否在运行
is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

# 停止服务
stop() {
  if ! is_running; then
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid" 2>/dev/null || true
  for _ in {1..30}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
}

# 启动服务
start() {
  if is_running; then
    echo "已在运行 (PID $(cat "$PID_FILE"))"
    return 0
  fi
  echo "启动: $PYTHON_BIN run.py"
  nohup "$PYTHON_BIN" "$ROOT/run.py" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  sleep 1
  if is_running; then
    echo "已启动 (PID $(cat "$PID_FILE"))"
  else
    echo "启动失败，日志: $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
  fi
}

# 直接执行 restart
stop
start
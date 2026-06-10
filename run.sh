#!/usr/bin/env bash
# 仅支持 restart 的极简脚本

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PID_FILE="$ROOT/run/aigc-api.pid"
LOG_FILE="$ROOT/logs/aigc-api.log"

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"

# 自动选择 Python 解释器（要求 >= 3.9）
MIN_PY_MAJOR=3
MIN_PY_MINOR=9

python_version_ok() {
  "$1" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 1)" 2>/dev/null
}

pick_python() {
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    if python_version_ok "$ROOT/.venv/bin/python"; then
      echo "$ROOT/.venv/bin/python"
      return
    fi
    echo "错误: .venv 的 Python 版本过低 ($("$ROOT/.venv/bin/python" -V 2>&1))，需要 >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR}" >&2
    echo "请重建虚拟环境:" >&2
    echo "  rm -rf .venv && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
  fi
  if [[ -x "/opt/miniconda3/envs/aigc/bin/python" ]] && python_version_ok "/opt/miniconda3/envs/aigc/bin/python"; then
    echo "/opt/miniconda3/envs/aigc/bin/python"
    return
  fi
  for py in python3.11 python3.10 python3; do
    if command -v "$py" &>/dev/null; then
      local bin
      bin="$(command -v "$py")"
      if python_version_ok "$bin"; then
        echo "$bin"
        return
      fi
    fi
  done
  echo "错误: 未找到 Python >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR}，请先安装 python3.11" >&2
  exit 1
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
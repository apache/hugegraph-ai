#!/bin/bash
# daemon.sh — ONTOGENY 演示环境守护脚本
#
# 用法: ./daemon.sh {start|stop|restart|status} [附加 ontogeny serve 参数]
# 示例:
#   ./daemon.sh start                 # 后台启动（日志写 $LOG_FILE）
#   ./daemon.sh start --port 8300     # 后台启动并透传附加参数
#   ./daemon.sh stop                  # 停止
#   ./daemon.sh restart               # 重启（stop + start）
#   ./daemon.sh status                # 查看运行状态
#
# 环境变量（可选覆盖）: HOST / PORT / DATA_DIR / PID_FILE / LOG_FILE

set -u

# ---- 业务环境（与此前 start.sh 一致） ----
export ONTOGENY_LLM_BASE_URL=${ONTOGENY_LLM_BASE_URL:-http://10.70.11.36:63302}
export ONTOGENY_LLM_MODEL=${ONTOGENY_LLM_MODEL:-qwen3.8:27b}
export HUGEGRAPH_URL=${HUGEGRAPH_URL:-http://10.22.32.25:18080}
# 平台自己创建的图，RocksDB 文件放哪。HugeGraph 的默认值是所有动态创建的图共用一个
# 目录，只有第一张能打开（第二张必然 "lock hold by current process"）；这里指向
# 该主机真实的数据目录。凭据不发到进程环境，由运维台写入 ontogeny_runtime_config。
export HUGEGRAPH_DATA_DIR=${HUGEGRAPH_DATA_DIR:-/home/dm/hugegraph-data}
# 动作的 webhook 效果（外部 HTTP 调用）投递白名单；空 = 全部拒绝。这里只放环回地址，
# 便于本地起个接收器验证；生产按实际目标主机配置。演示包里 ${WMS_WEBHOOK} 指向
# wms.example.test（不存在的演示域名），不在白名单内 → 事件被消费并记日志，不会反复重试。
export ONTOGENY_WEBHOOK_ALLOWLIST=${ONTOGENY_WEBHOOK_ALLOWLIST:-127.0.0.1}
# 想让演示里的 ${MES_WEBHOOK} / ${QMS_WEBHOOK} / ${ERP_WEBHOOK} 真的投递，在这里给出地址，
# 并把对应主机加进上面的白名单。未设置时事件被消费但不投递，日志写
# "not delivered ... (fix config and replay)" —— 配置错不该拖垮业务事务。
export ONTOGENY_ADMIN_USER=${ONTOGENY_ADMIN_USER:-admin}
export ONTOGENY_ADMIN_PASSWORD=${ONTOGENY_ADMIN_PASSWORD:-ontogeny@2026}

# ---- 守护参数 ----
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}
DATA_DIR=${DATA_DIR:-.ontogeny-daemon}
PID_FILE=${PID_FILE:-.ontogeny-daemon/ontogeny.pid}
PORT_FILE=${PORT_FILE:-.ontogeny-daemon/ontogeny.port}
LOG_FILE=${LOG_FILE:-.ontogeny-daemon/ontogeny.log}
STOP_TIMEOUT=${STOP_TIMEOUT:-15}

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"

# 仓库根与前端目录：stop 时按工作目录识别"属于本仓库"的 vite dev server，
# 其它项目（不同 cwd）的 vite 不会被动到
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$REPO_ROOT/web"
# 所有相对路径（.venv/bin/ontogeny、data-dir、pid/log 文件）都相对仓库根：
# 从任何目录调用本脚本都成立
cd "$REPO_ROOT"

pid_of() {
  [ -f "$PID_FILE" ] && cat "$PID_FILE" 2>/dev/null | tr -d '[:space:]'
}

is_running() {
  local pid; pid="$(pid_of)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

wait_gone() {
  local pid="$1" i=0
  while kill -0 "$pid" 2>/dev/null && [ "$i" -lt "$STOP_TIMEOUT" ]; do
    sleep 1; i=$((i + 1))
  done
  ! kill -0 "$pid" 2>/dev/null
}

do_start() {
  # 附加参数原样透传给 ontogeny serve；从中提取 --port 供就绪探测使用
  local extra=("$@") probe_port="$PORT"
  local i=0
  while [ "$i" -lt "${#extra[@]}" ]; do
    if [ "${extra[$i]}" = "--port" ] && [ $((i + 1)) -lt ${#extra[@]} ]; then
      probe_port="${extra[$((i + 1))]}"
    fi
    i=$((i + 1))
  done

  if is_running; then
    echo "ONTOGENY 已在运行 (pid $(pid_of), port $probe_port) — 如需重启用 ./daemon.sh restart"
    exit 0
  fi
  # 清理陈旧 pid 文件（进程已死的残留）
  rm -f "$PID_FILE"

  echo "启动 ONTOGENY (host=$HOST port=$probe_port, data=$DATA_DIR, log=$LOG_FILE)…"
  nohup .venv/bin/ontogeny serve --demo --data-dir "$DATA_DIR" --host "$HOST" --port "$PORT" ${extra[@]+"${extra[@]}"} >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  # 就绪探测：API 元数据端点可达即认为启动成功
  local i=0
  while [ "$i" -lt 40 ]; do
    if curl -sf -o /dev/null "http://127.0.0.1:${probe_port}/api/v1/meta/ontology"; then
      echo "$probe_port" > "$PORT_FILE"
      echo "ONTOGENY 已启动 (pid $(pid_of)) → http://127.0.0.1:${probe_port}/  · 日志: $LOG_FILE"
      return 0
    fi
    sleep 1; i=$((i + 1))
  done
  echo "启动超时：进程未在 40s 内就绪，详情见 $LOG_FILE" >&2
  exit 1
}

stop_vite() {
  # 前端 vite dev server 不归 pid 文件管（它是手动 npm run dev 起的），但留着
  # 会让人以为 ./daemon.sh stop "没杀干净"。按 cwd 识别本仓库的 vite 并停止；
  # 其它目录的 vite（别的项目）一律不碰。
  local pids pid cwd killed=0
  pids="$(pgrep -f 'vite' 2>/dev/null || true)"
  [ -z "$pids" ] && return 0
  for pid in $pids; do
    [ "$pid" = "$$" ] && continue
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
    case "$cwd" in
      "$WEB_DIR"|"$WEB_DIR"/*)
        if kill "$pid" 2>/dev/null; then
          killed=$((killed + 1))
        fi
        ;;
    esac
  done
  if [ "$killed" -gt 0 ]; then
    echo "已停止本仓库的 vite dev server（$killed 个进程）"
  fi
}

do_stop() {
  if ! is_running; then
    echo "ONTOGENY 未在运行"
    rm -f "$PID_FILE"
    stop_vite
    return 0
  fi
  local pid; pid="$(pid_of)"
  echo "停止 ONTOGENY (pid $pid)…"
  kill "$pid" 2>/dev/null
  if wait_gone "$pid"; then
    echo "已停止"
  else
    echo "优雅停止超时，强制结束…"
    kill -9 "$pid" 2>/dev/null
    sleep 1
  fi
  rm -f "$PID_FILE" "$PORT_FILE"
  stop_vite
}

do_status() {
  local port="$PORT"
  [ -f "$PORT_FILE" ] && port="$(cat "$PORT_FILE" 2>/dev/null || echo "$PORT")"
  if is_running; then
    local started=""; started="$(ps -o lstart= -p "$(pid_of)" 2>/dev/null | xargs)"
    echo "运行中 (pid $(pid_of), since ${started:-unknown}) → http://127.0.0.1:${port}/"
    echo "日志: $LOG_FILE"
  else
    echo "未运行"
    exit 3
  fi
}

case "${1:-}" in
  start)   shift; do_start "$@" ;;
  stop)    do_stop ;;
  restart) shift; do_stop; do_start "$@" ;;
  status)  do_status ;;
  *) echo "用法: $0 {start|stop|restart|status} [附加 ontogeny serve 参数]" >&2
     echo "      环境变量: HOST PORT DATA_DIR PID_FILE LOG_FILE STOP_TIMEOUT" >&2
     echo "      stop 会同时停止本仓库 web/ 下手动启动的 vite dev server（不影响其它项目）" >&2
     exit 2 ;;
esac

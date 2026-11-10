#!/usr/bin/env bash
# 로컬 통합 실행: KYT·Policy 엔진(모노레포) + Mock Gateway + Constellation Simulator + Backend
#
#   scripts/run-local.sh start    # 빌드 후 전체 기동 (Collector는 fixture 대체 구현 사용)
#   scripts/run-local.sh status   # /health 확인
#   scripts/run-local.sh stop     # 전체 종료
#
# 환경 변수
#   LAB_DIR                      solana-compliance-lab 경로 (기본 현재 워크스페이스)
#   LOCAL_COLLECTOR_ENABLED      true(기본)면 Collector 대신 $LAB_DIR/contracts/fixtures 사용.
#                                실제 Collector를 쓸 때는 false + COLLECTOR_URL 지정
#   CONSTELLATION_MOCK_ENABLED   true(기본)면 mock 버전(0.0.0-research-pending)에 화면 확인용 결과 반환
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAB_DIR="$(cd "${LAB_DIR:-$ROOT}" 2>/dev/null && pwd || echo "")"
RUN="$ROOT/.run"
mkdir -p "$RUN/logs"

export LOCAL_COLLECTOR_ENABLED="${LOCAL_COLLECTOR_ENABLED:-true}"
export CONSTELLATION_MOCK_ENABLED="${CONSTELLATION_MOCK_ENABLED:-true}"
export LOCAL_COLLECTOR_FIXTURES_DIR="${LOCAL_COLLECTOR_FIXTURES_DIR:-$LAB_DIR/contracts/fixtures}"

SERVICES="kyt:8001 policy:8002 gateway:8003 constellation:8004 backend:8080"

launch() { # name, workdir, command...
  local name=$1 dir=$2; shift 2
  if [ -f "$RUN/$name.pid" ] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then
    echo "  $name already running (pid $(cat "$RUN/$name.pid"))"; return
  fi
  (
    cd "$dir" || exit 1
    nohup "$@" > "$RUN/logs/$name.log" 2>&1 < /dev/null &
    echo $! > "$RUN/$name.pid"
  )
  echo "  $name started (log: .run/logs/$name.log)"
}

health() {
  for entry in $SERVICES; do
    local name=${entry%%:*} port=${entry##*:}
    if body=$(curl -fsS --max-time 2 "http://127.0.0.1:$port/health" 2>/dev/null); then
      echo "  [UP]   $name :$port  $body"
    else
      echo "  [DOWN] $name :$port"
    fi
  done
}

start() {
  echo "Building jars..."
  (cd "$ROOT" && ./mvnw -q -DskipTests package)

  echo "Starting services..."
  if [ -n "$LAB_DIR" ] && [ -x "$LAB_DIR/.venv/bin/python" ]; then
    launch kyt "$LAB_DIR" "$LAB_DIR/.venv/bin/python" -m kyt_engine --port 8001
    launch policy "$LAB_DIR" "$LAB_DIR/.venv/bin/python" -m policy_engine --port 8002
  else
    echo "  ! KYT/Policy 엔진을 건너뜀: \$LAB_DIR/.venv 가 없습니다. (README '사전 준비' 참고)"
  fi
  launch gateway "$ROOT" java -jar simulations/gateway/target/gateway-0.1.0.jar
  launch constellation "$ROOT" java -jar simulations/constellation/target/constellation-0.1.0.jar
  launch backend "$ROOT" java -jar apps/backend/target/backend-0.1.0.jar

  echo "Waiting for health checks..."
  for entry in $SERVICES; do
    curl -s -o /dev/null --retry 40 --retry-delay 1 --retry-connrefused "http://127.0.0.1:${entry##*:}/health" || true
  done
  health
}

stop() {
  for entry in $SERVICES; do
    local name=${entry%%:*}
    if [ -f "$RUN/$name.pid" ]; then
      kill "$(cat "$RUN/$name.pid")" 2>/dev/null && echo "  $name stopped" || true
      rm -f "$RUN/$name.pid"
    fi
  done
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) health ;;
  *) echo "usage: $0 [start|stop|status]"; exit 1 ;;
esac

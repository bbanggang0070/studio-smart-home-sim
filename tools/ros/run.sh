#!/usr/bin/env bash
# ============================================================================
#  이 프로젝트 전용 ROS 2 Jazzy 컨테이너 (SETUP §5 · 2026-10-10 결정 — 호스트 미설치)
#
#  - 이미지: studio-ros:jazzy (tools/ros/Dockerfile — 공식 ros:jazzy-ros-base + numpy · yaml)
#  - --network host --ipc host · ROS_DOMAIN_ID=7 · Fast DDS — Isaac Sim 컨테이너(tools/isaac/run.sh)와 같은 DDS 도메인
#  - 저장소는 /workspace/studio 에 마운트 · PYTHONPATH=scripts
#
#  사용:
#    tools/ros/run.sh build                              # 이미지 빌드 (처음 한 번)
#    tools/ros/run.sh node scripts/nodes/smart_home_node.py   # 노드 실행 (python3)
#    tools/ros/run.sh ros2 topic list                    # ros2 CLI
#    tools/ros/run.sh shell                              # 셸
#    tools/ros/run.sh stop                               # 남아 있는 이 프로젝트 ROS 컨테이너 모두 정리
# ============================================================================
set -euo pipefail

IMAGE="${STUDIO_ROS_IMAGE:-studio-ros:jazzy}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:-shell}"
shift || true

if [[ "$MODE" == "build" ]]; then
  exec docker build -t "$IMAGE" -f "$REPO/tools/ros/Dockerfile" "$REPO/tools/ros"
fi
if [[ "$MODE" == "stop" ]]; then                       # 이 프로젝트 ROS 컨테이너 모두 정리 (timeout 등으로 클라이언트만 끝난 경우)
  docker ps -q --filter label=studio=ros | xargs -r docker rm -f
  exit 0
fi

case "$MODE" in
  node)  CMD=(python3 "$@") ;;
  ros2)  CMD=(ros2 "$@") ;;
  shell) CMD=(bash) ;;
  *) echo "사용법: $0 {build | stop | node <script> [args] | ros2 <args> | shell}" >&2; exit 2 ;;
esac

TTY_ARGS=()
[[ -t 0 ]] && TTY_ARGS=(-it)

exec docker run --rm --init --label studio=ros "${TTY_ARGS[@]}" \
  --network host --ipc host \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-7}" -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 \
  -e PYTHONPATH=/workspace/studio/scripts -e PYTHONUNBUFFERED=1 \
  -v "$REPO:/workspace/studio:rw" -w /workspace/studio \
  "$IMAGE" bash -c 'source /opt/ros/jazzy/setup.bash && exec "$@"' _ "${CMD[@]}"

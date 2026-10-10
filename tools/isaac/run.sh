#!/usr/bin/env bash
# ============================================================================
#  이 프로젝트 전용 Isaac Sim 컨테이너 실행 (SETUP.md §4-A · 방법 A)
#
#  - 이미지: teleop-docker (Isaac Sim 5.1 · Isaac Lab 포함) — 다른 프로젝트와 공유하므로 이미지를 수정하지 않는다
#  - 이미지 entrypoint(다른 프로젝트 패키지 설치)를 우회하고, Isaac Sim 내장 python.sh 를 직접 쓴다
#  - 캐시 · 로그는 ~/docker/studio-isaac/ 에 따로 둔다 (다른 프로젝트 캐시와 섞지 않음)
#  - 저장소는 컨테이너의 /workspace/studio 에 마운트된다
#
#  사용:
#    tools/isaac/run.sh python tools/isaac/check_effort_sensor.py   # 헤드리스 파이썬 스크립트
#    tools/isaac/run.sh gui                                         # GUI 실행 (X11)
#    tools/isaac/run.sh shell                                       # 컨테이너 셸
# ============================================================================
set -euo pipefail

IMAGE="${STUDIO_ISAAC_IMAGE:-teleop-docker:latest}"
NAME="${STUDIO_ISAAC_NAME:-studio-isaac}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CACHE="${STUDIO_ISAAC_CACHE:-$HOME/docker/studio-isaac}"
ISAAC=/isaac-sim

mkdir -p "$CACHE"/{kit,ov,pip,glcache,computecache,logs,data,documents}

MODE="${1:-shell}"
shift || true

X11_ARGS=()
if [[ "$MODE" == "gui" ]]; then
  xhost +local:root >/dev/null 2>&1 || true
  X11_ARGS=(-e DISPLAY="${DISPLAY:-:0}" -v /tmp/.X11-unix:/tmp/.X11-unix:rw)
fi

# 컨테이너는 root 로 돈다 — 저장소에 만든 파일을 호스트 사용자 소유로 돌려준다 (호스트에서 고치고 지울 수 있게)
HOST_IDS="$(id -u):$(id -g)"
case "$MODE" in
  python) CMD=(bash -c '"$0" "$@"; rc=$?; find /workspace/studio -xdev -user 0 -not -path "*/.venv/*" -exec chown '"$HOST_IDS"' {} + 2>/dev/null; exit $rc' "$ISAAC/python.sh" "$@") ;;
  gui)    CMD=("$ISAAC/isaac-sim.sh" "$@") ;;
  shell)  CMD=(bash) ;;
  *) echo "사용법: $0 {python <script> [args] | gui | shell}" >&2; exit 2 ;;
esac

TTY_ARGS=()
[[ -t 0 ]] && TTY_ARGS=(-it)

exec docker run --rm "${TTY_ARGS[@]}" --name "$NAME" \
  --gpus all --network host --ipc host \
  -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y -e OMNI_KIT_ACCEPT_EULA=YES \
  -e ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-7}" \
  -e ROS_DISTRO=jazzy -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 \
  -e LD_LIBRARY_PATH="$ISAAC/exts/isaacsim.ros2.bridge/jazzy/lib" \
  -e PYTHONPATH="/workspace/studio/scripts" \
  "${X11_ARGS[@]}" \
  -v "$CACHE/kit:$ISAAC/kit/cache:rw" \
  -v "$CACHE/ov:/root/.cache/ov:rw" \
  -v "$CACHE/pip:/root/.cache/pip:rw" \
  -v "$CACHE/glcache:/root/.cache/nvidia/GLCache:rw" \
  -v "$CACHE/computecache:/root/.nv/ComputeCache:rw" \
  -v "$CACHE/logs:/root/.nvidia-omniverse/logs:rw" \
  -v "$CACHE/data:/root/.local/share/ov/data:rw" \
  -v "$CACHE/documents:/root/Documents:rw" \
  -v "$REPO:/workspace/studio:rw" \
  -w /workspace/studio \
  --entrypoint "" \
  "$IMAGE" "${CMD[@]}"

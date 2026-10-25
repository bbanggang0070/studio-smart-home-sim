#!/usr/bin/env bash
# BOPTEST 테스트 케이스 서버 (docs/11 필수 조치 5) — worker 이미지로 TestCase 를 직접 띄운다
#   tools/boptest/run_server.sh [testcase=bestest_air] [port=5000]
#   준비: git clone --depth 1 --branch v0.9.0 https://github.com/ibpsa/project1-boptest.git external/boptest
#         docker build -f service/worker/Dockerfile -t studio-boptest-worker:0.9.0 external/boptest
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TC="${1:-bestest_air}"
PORT="${2:-5000}"
NAME="studio-boptest-${TC}-${PORT}"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:5000" \
  -v "$ROOT/external/boptest/testcases/$TC:/testcase:ro" \
  -v "$ROOT/tools/boptest/tc_server.py:/tc_server.py:ro" \
  studio-boptest-worker:0.9.0 \
  bash -c ". /miniconda/bin/activate && conda activate pyfmi3 && python /tc_server.py"
echo "$NAME → http://127.0.0.1:${PORT}"

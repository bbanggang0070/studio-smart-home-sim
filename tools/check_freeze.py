"""판정 · 지표 동결 점검 (docs/11 §6.1 · §6.2 필수 조치 1) — 동결 뒤 판정 기준 · 지표 정의 · 목표값이 바뀌었는지 확인한다.

    uv run python tools/check_freeze.py            # 동결 목록과 비교 (바뀐 파일이 있으면 종료 코드 1)
    uv run python tools/check_freeze.py --write    # 지금 상태로 동결 목록을 새로 쓴다 (동결 개정 — docs/12 에 이유를 적을 것)

동결 대상 = config/freeze.yaml files (판정 기준 · 지표 계산 · 지표 → 목표 매핑 · 목표값).
thresholds.yaml 은 제어 계수까지 들어 있어 통째로 묶지 않고 targets 블록만 해시한다.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
FREEZE = REPO / "config" / "freeze.yaml"


def digest(entry: dict) -> str:
    path = REPO / entry["path"]
    if "yaml_key" in entry:                          # 파일 일부(점 경로)만 — 정렬된 YAML 로 직렬화해 해시
        node = yaml.safe_load(path.read_text(encoding="utf-8"))
        for k in entry["yaml_key"].split("."):
            node = node[k]
        data = yaml.safe_dump(node, sort_keys=True, allow_unicode=True).encode()
    else:
        data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    cfg = yaml.safe_load(FREEZE.read_text(encoding="utf-8"))
    changed = []
    for e in cfg["files"]:
        d = digest(e)
        if a.write:
            e["sha256"] = d
        elif d != e.get("sha256"):
            changed.append(e["path"] + (f" [{e['yaml_key']}]" if "yaml_key" in e else ""))
    if a.write:
        head = "".join(l for l in FREEZE.read_text(encoding="utf-8").splitlines(keepends=True) if l.startswith("#"))
        FREEZE.write_text(head + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"동결 목록 갱신: {len(cfg['files'])}개 — docs/12 동결 기록에 이유를 적을 것")
        return
    if changed:
        print("⚠️ 동결 뒤 바뀐 판정 · 지표 정의:")
        for c in changed:
            print("  -", c)
        sys.exit(1)
    print(f"동결 유지 — {len(cfg['files'])}개 모두 동결 때와 같다 (동결: {cfg['frozen_at']})")


if __name__ == "__main__":
    main()

"""판정 · 지표 동결 점검 (docs/11 §6.1 · §6.2 필수 조치 1) — 동결 뒤 판정 기준 · 지표 정의 · 목표값이 바뀌었는지 확인한다.

    uv run python tools/check_freeze.py                      # 판정 · 지표(files) 동결과 비교 (바뀌면 종료 코드 1)
    uv run python tools/check_freeze.py --group controller   # 제어기 동결과 비교 (필수 조치 4 보류 평가 전)
    uv run python tools/check_freeze.py --write [--group G]  # 지금 상태로 그 묶음을 새로 쓴다 (동결 개정 — docs/12 에 이유를 적을 것)

묶음: files = 판정 기준 · 지표 계산 · 지표 → 목표 매핑 · 목표값 · 보류 시나리오(사전 등록)
      controller = 제어 코드 · 제어 계수 · 학습 산출물 — 보류(held-out) 평가가 '동결된 제어기'를 채점했다는 근거
thresholds.yaml 은 제어 계수까지 들어 있어 files 에는 targets 블록만, controller 에는 파일 전체를 넣는다.
항목: path (파일) · path + yaml_key (파일 일부) · glob (여러 파일 — 경로 · 내용을 정렬해 한 해시로)
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
    if "glob" in entry:                              # 여러 파일 — 상대 경로 + 내용 (캐시 제외)
        h = hashlib.sha256()
        for f in sorted(p for p in REPO.glob(entry["glob"]) if p.is_file() and "__pycache__" not in p.parts):
            h.update(str(f.relative_to(REPO)).encode() + b"\0" + f.read_bytes() + b"\0")
        return h.hexdigest()
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
    ap.add_argument("--group", default="files", choices=["files", "controller", "all"])
    ap.add_argument("--config", help="동결 목록 파일 (기본 config/freeze.yaml · 난방 확장 트랙 = config/freeze_heating.yaml)")
    a = ap.parse_args()
    global FREEZE
    if a.config:
        FREEZE = REPO / a.config
    cfg = yaml.safe_load(FREEZE.read_text(encoding="utf-8"))
    groups = ["files", "controller"] if a.group == "all" else [a.group]
    changed = []
    entries = [e for g in groups for e in cfg.get(g) or []]
    for e in entries:
        d = digest(e)
        if a.write:
            e["sha256"] = d
        elif d != e.get("sha256"):
            changed.append(e.get("path", e.get("glob", "?")) + (f" [{e['yaml_key']}]" if "yaml_key" in e else ""))
    if a.write:
        head = "".join(l for l in FREEZE.read_text(encoding="utf-8").splitlines(keepends=True) if l.startswith("#"))
        FREEZE.write_text(head + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"동결 목록 갱신 ({'+'.join(groups)}): {len(entries)}개 — docs/12 동결 기록에 이유를 적을 것")
        return
    if changed:
        print("⚠️ 동결 뒤 바뀐 판정 · 지표 정의:")
        for c in changed:
            print("  -", c)
        sys.exit(1)
    when = " · ".join(f"{g} {cfg.get(g + '_frozen_at', cfg['frozen_at'])}" for g in groups)
    print(f"동결 유지 — {len(entries)}개 모두 동결 때와 같다 (동결: {when})")


if __name__ == "__main__":
    main()

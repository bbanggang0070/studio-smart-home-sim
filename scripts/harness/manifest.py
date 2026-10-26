"""실행 기록 (2026-10-26 · 재현성) — 결과 폴더에 어떤 코드 · 설정으로 돌렸는지 남긴다 (results/ 는 커밋하지 않으므로).

    write_manifest(out_dir, extra={...})  → <out_dir>/manifest.json
      git 커밋 · 브랜치 · 커밋하지 않은 변경 파일 · 동결 점검 결과 · 명령줄 · 시각 · 호스트
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _git(*args: str, strip: bool = True) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=20).stdout
        return out.strip() if strip else out
    except (OSError, subprocess.SubprocessError):
        return ""


def write_manifest(out_dir: str | Path, extra: dict | None = None) -> Path:
    out = Path(out_dir) if Path(out_dir).is_absolute() else REPO / out_dir
    out.mkdir(parents=True, exist_ok=True)
    dirty = [ln[3:] for ln in _git("status", "--porcelain", strip=False).splitlines() if ln and not ln[3:].startswith("results/")]
    try:
        chk = subprocess.run([sys.executable, str(REPO / "tools" / "check_freeze.py"), "--group", "all"],
                             cwd=REPO, capture_output=True, text=True, timeout=60)
        freeze = {"ok": chk.returncode == 0, "message": chk.stdout.strip().splitlines()[-1] if chk.stdout.strip() else ""}
    except (OSError, subprocess.SubprocessError):
        freeze = {"ok": None, "message": ""}
    m = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "commit": _git("rev-parse", "HEAD"),
         "branch": _git("rev-parse", "--abbrev-ref", "HEAD"), "uncommitted": dirty, "freeze": freeze,
         "argv": sys.argv, "python": sys.version.split()[0], "host": platform.node(), **(extra or {})}
    p = out / "manifest.json"
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return p

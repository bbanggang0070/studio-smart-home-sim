"""가전 · 창문 표시 검증 모음 (Scene v0.3) — tools/ros/visual_check.py 녹화에서 단계마다 해당 장치를 잘라 전후 변화량을 잰다.

    uv run python tools/analysis/visual_check_sheet.py   → results/media/visual_check/sheet.jpg · results/tables/visual_check.csv
단계 시각 = 브릿지 로그의 '표시 갱신' (녹화 시작 기준) · 프레임 = 시각 + settle_s (1 fps 녹화)
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "results" / "media" / "visual_check"
SETTLE_S = 2
# (녹화, 바뀌는 상태 이름, 표시 이름, 자를 영역 x0 y0 x1 y1 — 1280 × 720 기준)
CHECKS = [
    ("ac", "ac", "에어컨 (LED · 루버)", (380, 320, 840, 560)),
    ("bedside", "dehumidifier", "제습기 LED", (0, 380, 180, 640)),
    ("bedside", "humidifier", "가습기 LED · 분무", (680, 290, 830, 480)),
    ("bedside", "purifier_level", "청정기 LED 링", (860, 470, 1110, 720)),
    ("kitchen", "range_hood_level", "후드 LED · 등", (380, 0, 1280, 560)),
    ("kitchen", "appliance_power", "쿡탑 화구", (380, 280, 1280, 720)),
    ("window", "safety_state", "창문 안전 LED", (600, 300, 740, 390)),
]


OFFSET: dict[str, float] = {}


def events(cam: str) -> list[tuple[float, str, str]]:
    log = (BASE / f"{cam}_bridge.log").read_text(encoding="utf-8")
    t0 = float(re.search(r"\[(\d+\.\d+)\] \[isaac_actuator_bridge\]: 녹화", log).group(1))
    f0 = sorted((BASE / cam).glob("f*.jpg"))[0].stat().st_mtime   # 첫 프레임이 실제로 저장된 시각 (녹화 시작 로그보다 늦다)
    OFFSET[cam] = f0 - t0
    return [(float(t) - t0, k, v) for t, k, v in re.findall(r"\[(\d+\.\d+)\] \[isaac_actuator_bridge\]: 표시 갱신 (\S+) = (.*)", log)]


def frame(cam: str, t: float) -> np.ndarray:
    """프레임 k 의 시각 = 녹화 시작 + k × 저장 간격 (로그 '프레임 저장' 시각이 없으므로 파일 수정 시각으로 맞춘다)."""
    files = sorted((BASE / cam).glob("f*.jpg"))
    t0 = files[0].stat().st_mtime
    k = min(range(len(files)), key=lambda i: abs(files[i].stat().st_mtime - t0 - (t + SETTLE_S - OFFSET[cam])))
    return np.asarray(Image.open(files[k]).convert("RGB"))


def main() -> None:
    font = None
    for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"):
        if Path(f).exists():
            font = ImageFont.truetype(f, 16)
            break
    rows, tiles = [], []
    for cam, key, label, box in CHECKS:
        ev = [e for e in events(cam) if e[1] == key]
        prev = None
        for t, _, v in ev:
            img = frame(cam, t)[box[1]:box[3], box[0]:box[2]]
            if prev is not None:
                d = np.abs(img.astype(float) - prev.astype(float)).max(axis=2)
                rows.append({"device": label, "state": v[:60], "t_s": round(t, 1), "changed_px": int((d > 35).sum())})
            prev = img
            tile = Image.fromarray(img).resize((240, int(240 * img.shape[0] / img.shape[1])))
            canvas = Image.new("RGB", (240, 200), "black")
            canvas.paste(tile.crop((0, 0, 240, min(170, tile.size[1]))), (0, 30))
            ImageDraw.Draw(canvas).text((4, 4), f"{label}\n{v[:30]}", fill="white", font=font)
            tiles.append(canvas)
    cols = 6
    sheet = Image.new("RGB", (240 * cols, 200 * ((len(tiles) + cols - 1) // cols)), "black")
    for k, tl in enumerate(tiles):
        sheet.paste(tl, ((k % cols) * 240, (k // cols) * 200))
    sheet.save(BASE / "sheet.jpg", quality=90)
    df = pd.DataFrame(rows)
    (REPO / "results" / "tables").mkdir(parents=True, exist_ok=True)
    df.to_csv(REPO / "results" / "tables" / "visual_check.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()

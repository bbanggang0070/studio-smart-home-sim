"""참고문헌 DOI 검증 — Crossref API 로 실제 존재 · 제목 · 연도 · 학술지를 확인한다 (논문 docs/16 · 지어낸 문헌 금지).

    uv run python paper/refs/verify_dois.py <doi> [<doi> ...]     → paper/refs/crossref_cache.json 에 누적 · 화면 요약
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

CACHE = Path(__file__).with_name("crossref_cache.json")


def fetch(doi: str) -> dict | None:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers={"User-Agent": "studio-smart-home-sim/ref-check (mailto:hungue6559@naver.com)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["message"]
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def main() -> None:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for doi in sys.argv[1:]:
        doi = doi.strip().rstrip(".").lower()
        if doi not in cache:
            m = fetch(doi)
            if m and "error" not in m:
                cache[doi] = {"title": (m.get("title") or [""])[0], "year": (m.get("issued", {}).get("date-parts") or [[None]])[0][0],
                              "journal": (m.get("container-title") or [""])[0], "volume": m.get("volume"), "issue": m.get("issue"),
                              "page": m.get("page") or m.get("article-number"),
                              "authors": [f"{a.get('family','')}, {a.get('given','')}" for a in m.get("author", [])], "type": m.get("type")}
            else:
                cache[doi] = {"error": (m or {}).get("error", "없음")}
            time.sleep(0.5)
        c = cache[doi]
        print(("✗ " + doi + " — " + c["error"]) if "error" in c else f"✓ {doi} | {c['year']} | {c['journal'][:40]} | {c['title'][:90]} | {len(c['authors'])}명")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

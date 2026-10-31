"""Crossref 검색 — 후보 문헌 찾기 (선택은 사람이 · 고른 것은 verify_dois.py 로 다시 검증).

    uv run python paper/refs/search_crossref.py "<질의>" [--journal "Smart Structures and Systems"] [--rows 10] [--from 2015]
"""
import argparse, json, urllib.parse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("q"); ap.add_argument("--journal", default=""); ap.add_argument("--rows", type=int, default=10); ap.add_argument("--from", dest="frm", default="")
a = ap.parse_args()
params = {"query.bibliographic": a.q, "rows": a.rows, "select": "DOI,title,issued,container-title,author,is-referenced-by-count,type"}
filt = []
if a.journal:
    params["query.container-title"] = a.journal
if a.frm:
    filt.append(f"from-pub-date:{a.frm}")
if filt:
    params["filter"] = ",".join(filt)
url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
req = urllib.request.Request(url, headers={"User-Agent": "studio-smart-home-sim/ref-search (mailto:hungue6559@naver.com)"})
items = json.load(urllib.request.urlopen(req, timeout=40))["message"]["items"]
for it in items:
    y = (it.get("issued", {}).get("date-parts") or [[None]])[0][0]
    au = it.get("author", [{}])[0].get("family", "?") if it.get("author") else "?"
    print(f"{it['DOI']:<42} {y} | cit {it.get('is-referenced-by-count',0):>4} | {(it.get('container-title') or [''])[0][:30]:<30} | {au} | {(it.get('title') or [''])[0][:95]}")

#!/usr/bin/env python3
"""
Tencent Hunyuan pricing fetcher.

Scrapes https://cloud.tencent.com/document/product/1729/97731 (uses 元 not ¥),
converts to USD (FX=7.20), appends to history.csv when prices change.

source = "tencent-docs". Failure is logged but does not break the runner.
"""

import csv
import gzip
import re
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
HISTORY_CSV = ROOT / "data" / "history.csv"

DOC_URL = "https://cloud.tencent.com/document/product/1729/97731"
CNY_PER_USD = 7.20

TARGETS = {
    "hunyuan-turbos":     ["hunyuan-turbos"],
    "hunyuan-t1":         ["hunyuan-t1"],
    "hunyuan-a13b":       ["hunyuan-a13b"],
    "hunyuan-2-instruct": ["hy 2.0 instruct", "hy2.0 instruct"],
    "hunyuan-2-think":    ["hy 2.0 think", "hy2.0 think"],
    "hunyuan-large-role": ["hunyuan-large-role"],
}


def fetch_html() -> str:
    req = Request(DOC_URL, headers={
        "User-Agent": "Mozilla/5.0 ag-llm-pricing/0.4",
        "Accept-Encoding": "gzip, deflate",
    })
    with urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="ignore")


def extract_rows(html):
    """Walk the page sequentially: each model marker is followed by 输入：X元
    输出：Y元 inside its own row before the next model marker."""
    today = date.today().isoformat()
    alias_pattern = "|".join(re.escape(a) for aliases in TARGETS.values() for a in aliases)
    name_iter = list(re.finditer(alias_pattern, html, re.IGNORECASE))
    in_iter   = list(re.finditer(r"输入[：:]\s*(\d+\.?\d*)\s*元", html))
    out_iter  = list(re.finditer(r"输出[：:]\s*(\d+\.?\d*)\s*元", html))
    if not name_iter or not in_iter or not out_iter:
        return []

    events = []
    for nm in name_iter:
        text = nm.group(0).lower()
        for c, aliases in TARGETS.items():
            if any(a in text for a in aliases):
                events.append((nm.start(), "model", c))
                break
    for x in in_iter:
        events.append((x.start(), "in", float(x.group(1))))
    for x in out_iter:
        events.append((x.start(), "out", float(x.group(1))))
    events.sort()

    seen = {}
    i = 0
    while i < len(events):
        pos, kind, val = events[i]
        if kind != "model":
            i += 1; continue
        canon = val
        in_v, out_v = None, None
        j = i + 1
        while j < len(events) and events[j][1] != "model":
            _, k, v = events[j]
            if k == "in"  and in_v  is None: in_v  = v
            if k == "out" and out_v is None: out_v = v
            if in_v is not None and out_v is not None:
                break
            j += 1
        if canon not in seen and in_v is not None and out_v is not None:
            seen[canon] = {
                "date": today, "model": canon, "provider": "tencent",
                "std_in_cny": in_v, "std_out_cny": out_v,
            }
        i += 1
    return list(seen.values())


def to_history_rows(rows):
    out = []
    for r in rows:
        for field, cny in [("input_cost_per_token",  r["std_in_cny"]),
                           ("output_cost_per_token", r["std_out_cny"])]:
            out.append({
                "date": r["date"], "model": r["model"], "provider": r["provider"],
                "field": field,
                "price_usd_per_mtoken": round(cny / CNY_PER_USD, 6),
                "source": "tencent-docs", "source_ref": DOC_URL,
            })
    return out


def append_diff(new_rows):
    if not HISTORY_CSV.exists():
        print("  [hunyuan] history.csv missing, abort"); return 0
    existing = list(csv.DictReader(HISTORY_CSV.open()))
    latest = {(r["model"], r["field"]): float(r["price_usd_per_mtoken"])
              for r in existing if r["source"] == "tencent-docs"}
    appended = [r for r in new_rows
                if abs(latest.get((r["model"], r["field"]), -1) - r["price_usd_per_mtoken"]) > 1e-6]
    if not appended:
        print(f"  [hunyuan] {len(new_rows)} prices fetched, all unchanged"); return 0
    with HISTORY_CSV.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "model", "provider", "field",
                                          "price_usd_per_mtoken", "source", "source_ref"])
        w.writerows(appended)
    print(f"  [hunyuan] appended {len(appended)} new/changed rows")
    return len(appended)


def main():
    try:
        html = fetch_html()
    except Exception as e:
        print(f"  [hunyuan] fetch failed: {e}"); return
    rows = extract_rows(html)
    if not rows:
        print("  [hunyuan] WARN no rows parsed — page structure may have changed"); return
    print(f"  [hunyuan] parsed {len(rows)} models from Tencent docs:")
    for r in rows:
        print(f"    {r['model']:20s} ¥{r['std_in_cny']}/in ¥{r['std_out_cny']}/out")
    append_diff(to_history_rows(rows))


if __name__ == "__main__":
    main()
    sys.exit(0)

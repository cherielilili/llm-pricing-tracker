#!/usr/bin/env python3
"""
LLM Pricing Backfill — weekly snapshots from litellm git history.

Strategy:
  1. List commits touching `model_prices_and_context_window.json` since SINCE_DATE.
  2. Bucket by ISO week, take the latest commit per week (= "end-of-week price").
  3. Fetch the raw file at each commit, extract target models, write long-form CSV.

Output: 12_LLM_Pricing/data/history.csv
        columns: date, model, provider, field, price_usd_per_mtoken, source_commit
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_CSV = DATA_DIR / "history.csv"
SNAPSHOT_DIR = DATA_DIR / "snapshots"

REPO = "BerriAI/litellm"
FILE_PATH = "model_prices_and_context_window.json"
SINCE_DATE = "2026-01-01T00:00:00Z"

# Representative models. Hunyuan / Doubao absent from litellm → manual seed.
TARGET_MODELS = [
    # frontier western
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "gpt-5",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-4o",
    "o1",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite-preview",
    "xai/grok-4",
    "mistral/mistral-large-latest",
    # china open-weights / API
    "deepseek-chat",
    "deepseek/deepseek-v3.2",
    "moonshot/kimi-k2.5",
    "moonshot/kimi-k2.6",
    "minimax/MiniMax-M2.5",
    "zai/glm-4.7",
    "zai/glm-5",
    "dashscope/qwen-max",
]

PRICE_FIELDS = [
    "input_cost_per_token",
    "output_cost_per_token",
    "cache_read_input_token_cost",
    "cache_creation_input_token_cost",
    "input_cost_per_token_batches",
    "output_cost_per_token_batches",
]


def gh_get(url: str) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ag-llm-pricing/0.1"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def list_commits() -> list[dict]:
    """Page through commits touching the price file since SINCE_DATE."""
    out, page = [], 1
    while True:
        url = (
            f"https://api.github.com/repos/{REPO}/commits"
            f"?path={FILE_PATH}&since={SINCE_DATE}&per_page=100&page={page}"
        )
        batch = gh_get(url)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.3)
    return out


def pick_weekly(commits: list[dict]) -> list[tuple[str, str, str]]:
    """One commit per ISO week (the latest), returned oldest-first.
    Returns [(date_iso, sha, week_key), ...]."""
    seen: dict[str, tuple[str, str]] = {}
    for c in commits:
        d = c["commit"]["author"]["date"]
        dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
        wk = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        if wk not in seen or d > seen[wk][0]:
            seen[wk] = (d, c["sha"])
    rows = sorted([(d, sha, wk) for wk, (d, sha) in seen.items()])
    return rows


def fetch_file_at(sha: str) -> dict:
    url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{FILE_PATH}"
    req = Request(url, headers={"User-Agent": "ag-llm-pricing/0.1"})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def extract(d: dict, model: str) -> dict[str, float]:
    rec = d.get(model)
    if not rec:
        return {}
    out = {}
    for f in PRICE_FIELDS:
        v = rec.get(f)
        if v is not None:
            out[f] = float(v) * 1_000_000  # → $ / M tokens
    return out


def main():
    print(f"[backfill] listing commits since {SINCE_DATE} …")
    commits = list_commits()
    print(f"[backfill]   found {len(commits)} commits affecting price file")
    weekly = pick_weekly(commits)
    print(f"[backfill]   {len(weekly)} weekly snapshots to fetch")

    rows: list[dict] = []
    for i, (date_iso, sha, wk) in enumerate(weekly, 1):
        print(f"[backfill] [{i}/{len(weekly)}] {wk} {date_iso} {sha[:8]}")
        try:
            d = fetch_file_at(sha)
        except Exception as e:
            print(f"  ! fetch failed: {e}")
            continue
        snap_path = SNAPSHOT_DIR / f"{date_iso[:10]}_{sha[:8]}.json"
        snap_path.write_text(json.dumps(d, indent=0))
        for m in TARGET_MODELS:
            prices = extract(d, m)
            if not prices:
                continue
            provider = d[m].get("litellm_provider", "?")
            for field, price in prices.items():
                rows.append({
                    "date": date_iso[:10],
                    "model": m,
                    "provider": provider,
                    "field": field,
                    "price_usd_per_mtoken": round(price, 6),
                    "source": "litellm-git",
                    "source_ref": sha[:8],
                })
        time.sleep(0.4)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "model", "provider", "field",
                                          "price_usd_per_mtoken", "source", "source_ref"])
        w.writeheader()
        w.writerows(rows)
    print(f"[backfill] wrote {len(rows)} rows → {HISTORY_CSV}")


if __name__ == "__main__":
    sys.exit(main())

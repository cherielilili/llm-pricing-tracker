#!/usr/bin/env python3
"""
LLM Pricing Daily Fetch — incremental crosscheck from OpenRouter + DataLearner.

Run daily. Appends to history.csv only when:
  - source has no prior row for (model, field), OR
  - latest price for that (model, field, source) differs from incoming.

Sources:
  openrouter   — JSON API, 368+ models, current snapshot only
  datalearner  — HTML scrape, ~30 model entries (cache + standard rows)

Output rows share the same schema as backfill output:
  date, model, provider, field, price_usd_per_mtoken, source, source_ref
"""

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_CSV = DATA_DIR / "history.csv"

# Map our canonical (litellm) name → OpenRouter id. Skip if no mapping.
OPENROUTER_MAP = {
    "claude-opus-4-7":        "anthropic/claude-opus-4.7",
    "claude-sonnet-4-6":      "anthropic/claude-sonnet-4.6",
    "claude-haiku-4-5-20251001": "anthropic/claude-haiku-4.5",
    "gpt-5":                  "openai/gpt-5",
    "gpt-5.5":                "openai/gpt-5.5",
    "gpt-5.5-pro":            "openai/gpt-5.5-pro",
    "gpt-4o":                 "openai/gpt-4o",
    "o1":                     "openai/o1",
    "gemini-2.5-pro":         "google/gemini-2.5-pro",
    "gemini-2.5-flash":       "google/gemini-2.5-flash",
    "gemini-3.1-flash-lite-preview": "google/gemini-3.1-flash-lite-preview",
    "xai/grok-4":             "x-ai/grok-4",
    "mistral/mistral-large-latest": "mistralai/mistral-large",
    "deepseek-chat":          "deepseek/deepseek-chat",
    "deepseek/deepseek-v3.2": "deepseek/deepseek-v3.2",
    "moonshot/kimi-k2.5":     "moonshotai/kimi-k2.5",
    "moonshot/kimi-k2.6":     "moonshotai/kimi-k2.6",
    "minimax/MiniMax-M2.5":   "minimax/minimax-m2.5",
    "zai/glm-4.7":            "z-ai/glm-4.7",
    "zai/glm-5":              "z-ai/glm-5",
    "dashscope/qwen-max":     "qwen/qwen-max",
}

# DataLearner model-name → our canonical name (best-effort, page uses informal names).
# Only models we care to crosscheck. Page provides 缓存 (cache) and 标准 (standard) prices.
DATALEARNER_MAP = {
    # datalearner display name : canonical
    "GPT-5":       "gpt-5",
    "GPT-5.5":     "gpt-5.5",
    "GPT-5.2":     None,           # page shows GPT-5.2, not in our list — skip but record
    "Opus 4.7":    "claude-opus-4-7",
    "Opus 4.5":    None,
    "Sonnet 4.6":  "claude-sonnet-4-6",
    "Sonnet 4.7":  None,
    "Haiku 4.5":   "claude-haiku-4-5-20251001",
    "Gemini 2.5 Pro":   "gemini-2.5-pro",
    "Gemini 2.5 Flash": "gemini-2.5-flash",
    "Gemini 3.0 Flash": None,
    "DeepSeek V3":    "deepseek-chat",
    "DeepSeek V3.1":  "deepseek-chat",
    "DeepSeek V3.2":  "deepseek/deepseek-v3.2",
    "Grok 4":         "xai/grok-4",
    "Grok 4.1 Fast":  None,
    "M2.1":           None,
    "M2.5":           "minimax/MiniMax-M2.5",
    "GLM-4.7":        "zai/glm-4.7",
    "GLM-5":          "zai/glm-5",
    "Kimi K2.5":      "moonshot/kimi-k2.5",
    "Kimi K2.6":      "moonshot/kimi-k2.6",
    "qwen-max":       "dashscope/qwen-max",
    "qwen3-max":      None,
}

CNY_PER_USD = 7.20  # FX for ¥-priced rows from DataLearner


def http_get(url: str, ua="ag-llm-pricing/0.3") -> bytes:
    req = Request(url, headers={"User-Agent": ua,
                                "Accept": "application/json, text/html"})
    with urlopen(req, timeout=30) as r:
        return r.read()


# ---------- OpenRouter ----------

def fetch_openrouter() -> list[dict]:
    raw = http_get("https://openrouter.ai/api/v1/models")
    data = json.loads(raw)["data"]
    by_id = {m["id"]: m for m in data}
    today = date.today().isoformat()
    rows = []
    for canon, or_id in OPENROUTER_MAP.items():
        m = by_id.get(or_id)
        if not m:
            print(f"  [openrouter] miss: {or_id}")
            continue
        p = m.get("pricing", {})
        # OpenRouter uses prompt/completion in $/token (not $/M)
        for or_field, our_field in [("prompt", "input_cost_per_token"),
                                    ("completion", "output_cost_per_token")]:
            v = p.get(or_field)
            if v is None or float(v) == 0:
                continue
            rows.append({
                "date": today,
                "model": canon,
                "provider": (m.get("id") or "").split("/")[0],
                "field": our_field,
                "price_usd_per_mtoken": round(float(v) * 1_000_000, 6),
                "source": "openrouter",
                "source_ref": or_id,
            })
    print(f"  [openrouter] extracted {len(rows)} rows for {len(OPENROUTER_MAP)} target models")
    return rows


# ---------- DataLearner ----------

# Header columns observed on https://www.datalearner.com/ai-models/api-prices :
# 模型名称 | 供应商 | 计费模式(缓存/批量+标准) | 输入价_缓存 | 输出价_缓存 | 输入价_标准 | 输出价_标准 | 单位 | 输入模态 | 输出模态 | 发布时间

def fetch_datalearner() -> list[dict]:
    try:
        raw = http_get("https://www.datalearner.com/ai-models/api-prices",
                       ua="Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/605.1.15")
    except Exception as e:
        print(f"  [datalearner] fetch failed: {e}")
        return []
    html = raw.decode("utf-8", errors="ignore")
    today = date.today().isoformat()
    rows = []

    # extract single big table
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
    if not tables:
        print("  [datalearner] no tables found")
        return []
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", tables[0], re.DOTALL)
    for tr in trs[1:]:  # skip header
        # strip tags, split by tag boundary
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        text_cells = [re.sub(r"<[^>]+>", " ", c).replace("&nbsp;", " ").strip() for c in cells]
        text_cells = [re.sub(r"\s+", " ", c) for c in text_cells]
        if len(text_cells) < 4:
            continue

        model_name = text_cells[0].strip()
        if not model_name:
            continue
        canon = DATALEARNER_MAP.get(model_name)
        if canon is None and model_name not in DATALEARNER_MAP:
            continue  # unmapped, skip
        if canon is None:
            continue  # explicitly skipped

        # find all $-prefixed and ¥-prefixed numbers in row
        prices_usd = [float(x) for x in re.findall(r"\$\s*([\d.]+)", " ".join(text_cells))]
        prices_cny = [float(x) for x in re.findall(r"¥\s*([\d.]+)", " ".join(text_cells))]

        # heuristic: 4 numbers = [cache_in, cache_out, std_in, std_out]
        # 2 numbers = [std_in, std_out]  (no cache offered)
        def to_usd(arr):
            if all(p in prices_usd for p in arr): return arr
            return [v / CNY_PER_USD for v in arr] if arr and arr[0] in prices_cny else arr

        nums = prices_usd if prices_usd else [v / CNY_PER_USD for v in prices_cny]
        if not nums:
            continue

        if len(nums) >= 4:
            cache_in, cache_out, std_in, std_out = nums[0], nums[1], nums[2], nums[3]
            mapping = [
                ("cache_read_input_token_cost",  cache_in),
                ("cache_creation_input_token_cost", cache_in),  # DL doesn't split
                ("input_cost_per_token",         std_in),
                ("output_cost_per_token",        std_out),
            ]
        elif len(nums) >= 2:
            std_in, std_out = nums[-2], nums[-1]
            mapping = [
                ("input_cost_per_token",  std_in),
                ("output_cost_per_token", std_out),
            ]
        else:
            continue

        provider = text_cells[1] if len(text_cells) > 1 else "?"
        for field, price in mapping:
            if price <= 0:
                continue
            rows.append({
                "date": today,
                "model": canon,
                "provider": provider,
                "field": field,
                "price_usd_per_mtoken": round(price, 6),
                "source": "datalearner",
                "source_ref": model_name,
            })
    print(f"  [datalearner] extracted {len(rows)} rows")
    return rows


# ---------- diff & write ----------

def load_history() -> list[dict]:
    if not HISTORY_CSV.exists():
        return []
    with HISTORY_CSV.open() as f:
        return list(csv.DictReader(f))


def append_diff(existing: list[dict], new_rows: list[dict]) -> int:
    """Only append rows where price differs from latest existing row of same key."""
    # latest price per (model, field, source)
    latest: dict[tuple, float] = {}
    for r in existing:
        key = (r["model"], r["field"], r["source"])
        # rows are appended over time; later row supersedes
        latest[key] = float(r["price_usd_per_mtoken"])

    appended = []
    for r in new_rows:
        key = (r["model"], r["field"], r["source"])
        prev = latest.get(key)
        if prev is None or abs(prev - float(r["price_usd_per_mtoken"])) > 1e-6:
            appended.append(r)

    if not appended:
        print("  no price changes vs last snapshot — nothing to append")
        return 0

    fieldnames = ["date", "model", "provider", "field",
                  "price_usd_per_mtoken", "source", "source_ref"]
    write_header = not HISTORY_CSV.exists()
    with HISTORY_CSV.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        w.writerows(appended)
    print(f"  appended {len(appended)} new/changed rows → {HISTORY_CSV}")
    return len(appended)


def main():
    print("[fetch] OpenRouter …")
    or_rows = fetch_openrouter()
    print("[fetch] DataLearner …")
    dl_rows = fetch_datalearner()
    existing = load_history()
    print(f"[fetch] existing history rows: {len(existing)}")
    n1 = append_diff(existing, or_rows)
    # reload after first append so dedup knows about OR rows
    existing = load_history()
    n2 = append_diff(existing, dl_rows)
    print(f"[fetch] total appended this run: OR={n1}  DL={n2}")


if __name__ == "__main__":
    sys.exit(main())

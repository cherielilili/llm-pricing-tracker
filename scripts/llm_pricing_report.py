#!/usr/bin/env python3
"""
LLM 定价趋势报告 v3 — 中文版,黑灰蓝白配色,变化摘要置顶。

Reads:
  12_LLM_Pricing/data/history.csv      — 自动从 litellm git
  12_LLM_Pricing/data/seed_manual.csv  — 文本模型手工 seed (Hunyuan / Doubao 等)
  12_LLM_Pricing/data/seed_media.csv   — 非 token 模型 (视频生成: Seedance / Sora / Veo / Kling / Runway)

Output:
  12_LLM_Pricing/reports/<date>_llm_pricing.html — 自包含 inline Plotly,可分享给非 Obsidian 用户。
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_CSV = DATA_DIR / "history.csv"
SEED_MANUAL = DATA_DIR / "seed_manual.csv"
SEED_MEDIA = DATA_DIR / "seed_media.csv"
REPORTS_DIR = ROOT / "reports"

# 标准化 provider 显示名 (litellm 原始名 → 显示名)
PROVIDER_REMAP = {
    "vertex_ai-language-models": "google",
    "gemini": "google",
    "cohere_chat": "cohere",
    "dashscope": "alibaba",
    "zai": "zhipu",
}

# 黑灰蓝白配色 — 蓝色家族区分 provider
PROVIDER_COLOR = {
    "anthropic": "#1f3a5f",
    "openai":    "#2d5f8b",
    "google":    "#4a7ba6",
    "xai":       "#0f1e33",
    "deepseek":  "#5b8fb9",
    "moonshot":  "#7aa3c7",
    "minimax":   "#94b4d4",
    "mistral":   "#3d5a80",
    "cohere":    "#6c8ebf",
    "alibaba":   "#506b8e",
    "zhipu":     "#3a5a7c",
    "tencent":   "#2a4a6a",
    "bytedance": "#22618c",
    "kuaishou":  "#7d9ec0",
    "runway":    "#1a2a44",
}
DEFAULT_COLOR = "#888"

FIELD_LABEL = {
    "input_cost_per_token":            "输入",
    "output_cost_per_token":           "输出",
    "cache_read_input_token_cost":     "缓存读取",
    "cache_creation_input_token_cost": "缓存写入",
    "input_cost_per_token_batches":    "Batch 输入",
    "output_cost_per_token_batches":   "Batch 输出",
}

FIELD_GLOSSARY = [
    ("输入 Input",         "标准 prompt token,按模型基础价计费。"),
    ("输出 Output",        "生成的 completion token,通常是输入价的 3-5 倍。"),
    ("缓存读取 Cache read", "命中 prompt cache 后的 token 价,通常是输入价的 1/10。Anthropic / OpenAI / DeepSeek / GLM 都支持。"),
    ("缓存写入 Cache write","首次写入 cache 的 token 价,通常 1.25× 输入价。≥2 次复用后才划算。"),
    ("Batch 输入",          "Batch API 异步处理的输入价,普遍 50% off,SLA 约 24 小时。OpenAI / Anthropic / Gemini 支持。"),
    ("Batch 输出",          "Batch API 异步处理的输出价,同样 50% off。"),
]

UNIT_LABEL = {
    "per_5s_1080p_video":      "每 5 秒 1080p 视频",
    "per_million_video_tokens":"每 100 万视频 token",
    "per_second":              "每秒",
    "per_second_audio_off":    "每秒 (无音频)",
    "per_second_audio_on":     "每秒 (含音频)",
    "per_5s_video":            "每 5 秒视频",
    "per_extra_second":        "超出 5 秒后每秒",
}


def normalize_provider(p):
    p = (p or "").lower()
    return PROVIDER_REMAP.get(p, p)


def provider_color(p):
    return PROVIDER_COLOR.get(normalize_provider(p), DEFAULT_COLOR)


def stepped_line(df, fields, end_date, height=420, include_plotlyjs=False):
    sub = df[df["field"].isin(fields)].copy()
    if sub.empty:
        return '<div style="padding:24px;color:#777;font-size:13px;">暂无数据。</div>'
    sub["date"] = pd.to_datetime(sub["date"])
    sub["provider_norm"] = sub["provider"].apply(normalize_provider)
    fig = go.Figure()
    end_dt = pd.Timestamp(end_date)
    field_dash = {f: ("solid" if i == 0 else "dot") for i, f in enumerate(fields)}
    for (model, field), g in sub.sort_values("date").groupby(["model", "field"]):
        last = g.iloc[-1].copy()
        last["date"] = end_dt
        gx = pd.concat([g, last.to_frame().T], ignore_index=True)
        provider = g["provider_norm"].iloc[0]
        suffix = f" · {FIELD_LABEL.get(field, field)}" if len(fields) > 1 else ""
        fig.add_trace(go.Scatter(
            x=gx["date"], y=gx["price_usd_per_mtoken"],
            mode="lines+markers",
            line=dict(shape="hv", width=1.8, color=provider_color(provider), dash=field_dash[field]),
            marker=dict(size=4),
            name=f"{model}{suffix}",
            legendgroup=provider,
            legendgrouptitle_text=provider,
            hovertemplate="<b>%{fullData.name}</b><br>%{x|%Y-%m-%d}<br>$%{y:.4f} / 100万 token<extra></extra>",
        ))
    fig.update_layout(
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        font=dict(family="-apple-system,'PingFang SC',system-ui,sans-serif", size=12, color="#222"),
        xaxis=dict(showgrid=True, gridcolor="#eee", linecolor="#ddd", title=""),
        yaxis=dict(showgrid=True, gridcolor="#eee", linecolor="#ddd",
                   title="美元 / 100万 token", type="log"),
        legend=dict(groupclick="toggleitem", bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="#ddd", borderwidth=1, font=dict(size=11)),
        hovermode="closest",
        margin=dict(l=60, r=20, t=20, b=40),
        height=height,
    )
    return fig.to_html(full_html=False, include_plotlyjs=include_plotlyjs)


SOURCE_TAG = {  # short superscript markers for source provenance
    "litellm-git":  "L",
    "openrouter":   "OR",
    "datalearner":  "DL",
    "tencent-docs": "T",
    "manual_seed":  "M",
}


def latest_table_html(df):
    """For each (model, field), pick the cheapest price across all sources.
    Highlight cheapest (green) / priciest (red) per column. Tag cell with source."""
    df = df.copy()
    df["provider"] = df["provider"].apply(normalize_provider)
    # latest row per (model, field, source) — newest date wins
    latest = df.sort_values("date").groupby(["model", "provider", "field", "source"]).tail(1)
    # pick the cheapest source per (model, provider, field)
    cheapest = (latest.sort_values("price_usd_per_mtoken")
                      .groupby(["model", "provider", "field"]).head(1))
    pivot_price  = cheapest.pivot_table(index=["provider", "model"], columns="field",
                                        values="price_usd_per_mtoken", aggfunc="first")
    pivot_source = cheapest.pivot_table(index=["provider", "model"], columns="field",
                                        values="source", aggfunc="first")

    cols_order = [c for c in FIELD_LABEL.keys() if c in pivot_price.columns]
    pivot_price  = pivot_price.reindex(columns=cols_order)
    pivot_source = pivot_source.reindex(columns=cols_order)

    col_min = {c: pivot_price[c].min(skipna=True) for c in cols_order}
    col_max = {c: pivot_price[c].max(skipna=True) for c in cols_order}

    header = "".join(f"<th>{FIELD_LABEL[c]}</th>" for c in cols_order)
    body_rows = []
    sources_seen = set()
    for (provider, model), row in pivot_price.iterrows():
        cells = [f"<td>{provider}</td>", f"<td>{model}</td>"]
        for c in cols_order:
            v = row[c]
            if pd.isna(v):
                cells.append('<td class="muted">—</td>')
                continue
            src = pivot_source.loc[(provider, model), c]
            sources_seen.add(src)
            tag = SOURCE_TAG.get(src, "?")
            cls = ""
            if abs(v - col_min[c]) < 1e-9 and col_min[c] != col_max[c]:
                cls = "cheapest"
            elif abs(v - col_max[c]) < 1e-9 and col_min[c] != col_max[c]:
                cls = "priciest"
            cells.append(
                f'<td class="{cls}" title="source: {src}">'
                f'${v:.3f}<sup class="src-tag">{tag}</sup></td>'
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    legend = ('<div class="hint" style="font-size:12px;color:#6b7280;margin-bottom:8px;">'
              '<span class="cheapest" style="padding:1px 6px;border-radius:3px;">最便宜</span> · '
              '<span class="priciest" style="padding:1px 6px;border-radius:3px;">最贵</span> '
              ' · 每列独立计算,不参与跨列比较。')
    if sources_seen:
        legend += "<br/>价格取多源中的最低值,右上角标注来源 — "
        legend += " · ".join(f"<b>{SOURCE_TAG[s]}</b>={s}" for s in sorted(sources_seen) if s in SOURCE_TAG)
        legend += "</div>"
    else:
        legend += "</div>"

    return legend + (
        f'<table class="data-table"><thead><tr>'
        f'<th>厂商</th><th>模型</th>{header}'
        f'</tr></thead><tbody>{"".join(body_rows)}</tbody></table>'
    )


def changes_summary(df):
    out = []
    for (model, field), g in df.sort_values("date").groupby(["model", "field"]):
        if g["price_usd_per_mtoken"].nunique() > 1:
            first, last = g.iloc[0], g.iloc[-1]
            delta = (last["price_usd_per_mtoken"] - first["price_usd_per_mtoken"]) / first["price_usd_per_mtoken"] * 100
            out.append({
                "model": model, "field": FIELD_LABEL.get(field, field),
                "from": f'${first["price_usd_per_mtoken"]:.3f}',
                "to":   f'${last["price_usd_per_mtoken"]:.3f}',
                "delta_pct": delta,
                "first_date": first["date"], "last_date": last["date"],
            })
    return sorted(out, key=lambda r: r["delta_pct"])


def media_table_html():
    if not SEED_MEDIA.exists():
        return ""
    df = pd.read_csv(SEED_MEDIA)
    has_norm = "usd_per_10s_norm" in df.columns
    rows = []
    for _, r in df.iterrows():
        unit = UNIT_LABEL.get(r["unit"], r["unit"].replace("_", " "))
        price_cell = '<span class="muted">待补充</span>' if pd.isna(r["price_usd"]) else f"${r['price_usd']:.2f}"
        if has_norm:
            norm = r.get("usd_per_10s_norm")
            norm_cell = ('<span class="muted">—</span>' if pd.isna(norm)
                         else f'<b style="color:var(--accent)">${norm:.2f}</b>')
        note = r.get("note", "")
        if isinstance(note, str) and note.startswith("http"):
            note_cell = f"<a href='{note}' target='_blank'>来源</a>"
        else:
            note_cell = note if isinstance(note, str) else ""
        norm_col = f"<td>{norm_cell}</td>" if has_norm else ""
        rows.append(
            f"<tr><td>{r['model']}</td><td>{r['provider']}</td>"
            f"<td>{unit}</td><td>{price_cell}</td>{norm_col}"
            f"<td class='muted'>{note_cell}</td></tr>"
        )
    norm_th = '<th title="按10秒标准视频折算,默认设置">归一价 / 10秒</th>' if has_norm else ""
    return f"""<table class="data-table"><thead><tr>
        <th>模型</th><th>厂商</th><th>计费单位</th><th>原价 (美元)</th>{norm_th}<th>说明</th>
        </tr></thead><tbody>{''.join(rows)}</tbody></table>"""


def crosscheck_table_html(df):
    """Compare latest input/output prices across sources for each model."""
    sub = df[df["field"].isin(["input_cost_per_token", "output_cost_per_token"])]
    latest = sub.sort_values("date").groupby(["model", "field", "source"]).tail(1)
    rows_html = []
    for model, g in latest.groupby("model"):
        for field in ["input_cost_per_token", "output_cost_per_token"]:
            sub2 = g[g["field"] == field]
            if sub2.empty:
                continue
            prices = {r["source"]: float(r["price_usd_per_mtoken"]) for _, r in sub2.iterrows()}
            vals = list(prices.values())
            if len(vals) < 2:
                continue  # only show rows with 2+ sources
            div = (max(vals) - min(vals)) / min(vals) * 100
            cls = "diverge-high" if div > 25 else "diverge-mid" if div > 5 else "diverge-low"
            cells = "".join(
                f"<td>${prices[s]:.3f}</td>" if s in prices else "<td class='muted'>—</td>"
                for s in ["litellm-git", "openrouter", "datalearner"]
            )
            rows_html.append(
                f"<tr class='{cls}'><td>{model}</td><td>{FIELD_LABEL[field]}</td>"
                f"{cells}<td><b>{div:.0f}%</b></td></tr>"
            )
    if not rows_html:
        return '<div class="empty">尚无跨源数据。</div>'
    return f"""<table class="data-table"><thead><tr>
        <th>模型</th><th>字段</th><th>litellm-git</th><th>openrouter</th>
        <th>datalearner</th><th>最大背离</th>
        </tr></thead><tbody>{''.join(rows_html)}</tbody></table>"""


def main():
    df_all = pd.read_csv(HISTORY_CSV)
    # historical trend uses litellm-git only (only source with real history)
    df = df_all[df_all["source"] == "litellm-git"].copy()
    # latest-prices view: ALL sources + manual seed (to find cheapest across channels)
    if SEED_MANUAL.exists():
        sm = pd.read_csv(SEED_MANUAL)
        sm = sm[sm["price_usd_per_mtoken"].notna()].copy()
        sm["source"] = "manual_seed"
        if "source_ref" not in sm.columns:
            sm["source_ref"] = ""
        cols = ["date", "model", "provider", "field", "price_usd_per_mtoken", "source", "source_ref"]
        df_full = pd.concat([df_all[cols], sm[cols]], ignore_index=True)
    else:
        df_full = df_all.copy()

    today = datetime.now().strftime("%Y-%m-%d")
    n_models = df_full["model"].nunique()
    n_obs = len(df)
    date_min, date_max = df["date"].min(), df["date"].max()
    changes = changes_summary(df)

    fig_in    = stepped_line(df, ["input_cost_per_token"],  today, include_plotlyjs="inline")
    fig_out   = stepped_line(df, ["output_cost_per_token"], today)
    fig_cache = stepped_line(df, ["cache_read_input_token_cost", "cache_creation_input_token_cost"], today)
    fig_batch = stepped_line(df, ["input_cost_per_token_batches", "output_cost_per_token_batches"], today)

    table_html = latest_table_html(df_full)
    media_html = media_table_html()
    crosscheck_html = crosscheck_table_html(df_all)
    n_or  = (df_all["source"] == "openrouter").sum()
    n_dl  = (df_all["source"] == "datalearner").sum()

    if changes:
        chg_rows = "".join(
            f'<tr><td>{c["model"]}</td><td>{c["field"]}</td>'
            f'<td>{c["from"]}</td><td>{c["to"]}</td>'
            f'<td class="{"down" if c["delta_pct"] < 0 else "up"}">{c["delta_pct"]:+.1f}%</td>'
            f'<td class="muted">{c["first_date"]} → {c["last_date"]}</td></tr>'
            for c in changes
        )
        chg_block = f"""<table class="data-table"><thead><tr>
            <th>模型</th><th>字段</th><th>原价</th><th>新价</th><th>涨跌</th><th>变动区间</th>
            </tr></thead><tbody>{chg_rows}</tbody></table>"""
    else:
        chg_block = '<div class="empty">区间内未检测到价格调整。</div>'

    glossary_rows = "".join(
        f"<tr><td><b>{name}</b></td><td>{desc}</td></tr>" for name, desc in FIELD_GLOSSARY
    )

    days = (pd.to_datetime(date_max) - pd.to_datetime(date_min)).days

    html = f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<title>LLM Token 定价趋势 — {today}</title>
<style>
  :root {{
    --bg:#ffffff; --surface:#fafafa; --border:#e5e7eb;
    --text:#111827; --muted:#6b7280; --accent:#1f3a5f;
    --up:#b91c1c; --down:#0e7490;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 40px; background:var(--bg); color:var(--text);
          font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','SF Pro Text',
                      'Helvetica Neue',system-ui,sans-serif;
          font-size:14px; line-height:1.6; max-width:1200px; margin-left:auto; margin-right:auto; }}
  header {{ border-bottom:1px solid var(--border); padding-bottom:16px; margin-bottom:24px; }}
  h1 {{ margin:0; font-size:22px; font-weight:600; letter-spacing:0; color:var(--text); }}
  .sub {{ color:var(--muted); font-size:13px; margin-top:4px; }}
  .pill {{ display:inline-block; padding:1px 8px; background:#eef2f7; color:var(--accent);
          border-radius:3px; font-size:11px; margin-left:8px; font-weight:500; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
            gap:12px; margin-bottom:24px; }}
  .card {{ background:var(--surface); border:1px solid var(--border); border-radius:6px;
           padding:12px 16px; }}
  .card .label {{ font-size:11px; color:var(--muted); letter-spacing:0.04em; font-weight:500; }}
  .card .val {{ font-size:22px; font-weight:600; margin-top:4px; color:var(--text); }}
  section {{ margin-bottom:32px; }}
  h2 {{ font-size:15px; font-weight:600; margin:0 0 12px; padding-bottom:6px;
        border-bottom:1px solid var(--border); }}
  .chart-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media (max-width:900px) {{ .chart-grid {{ grid-template-columns:1fr; }} }}
  .chart-card {{ border:1px solid var(--border); border-radius:6px; padding:12px;
                 background:var(--bg); }}
  .chart-card h3 {{ margin:0 0 8px; font-size:13px; font-weight:600; color:var(--text); }}
  .chart-card .hint {{ font-size:11px; color:var(--muted); margin-bottom:6px; }}
  table.data-table {{ width:100%; border-collapse:collapse; font-size:13px;
                       font-variant-numeric:tabular-nums; }}
  .data-table th, .data-table td {{ padding:7px 10px; text-align:left;
                                     border-bottom:1px solid var(--border); }}
  .data-table th {{ background:var(--surface); font-weight:600; color:var(--muted);
                    font-size:12px; letter-spacing:0.02em; }}
  .data-table tbody tr:hover {{ background:#f9fafb; }}
  td.down {{ color:var(--down); font-weight:600; }}
  td.up   {{ color:var(--up);   font-weight:600; }}
  td.muted, .muted {{ color:var(--muted); }}
  tr.diverge-high {{ background:#fff1f2; }}
  tr.diverge-high td:last-child {{ color:var(--up); }}
  tr.diverge-mid  {{ background:#fffbeb; }}
  tr.diverge-mid  td:last-child {{ color:#a16207; }}
  tr.diverge-low td:last-child {{ color:var(--muted); }}
  td.cheapest, span.cheapest {{ background:#ecfdf5; color:#047857; font-weight:600; }}
  td.priciest, span.priciest {{ background:#fef2f2; color:#b91c1c; font-weight:600; }}
  sup.src-tag {{ font-size:9px; color:var(--muted); margin-left:3px; font-weight:400; }}
  .empty {{ padding:16px; background:var(--surface); border:1px solid var(--border);
            border-radius:6px; color:var(--muted); text-align:center; font-size:13px; }}
  .glossary {{ background:var(--surface); border:1px solid var(--border); border-radius:6px;
              padding:8px 14px; }}
  .glossary table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  .glossary td {{ padding:5px 8px; vertical-align:top; }}
  .glossary td:first-child {{ width:160px; color:var(--accent); }}
  footer {{ margin-top:32px; padding-top:16px; border-top:1px solid var(--border);
            font-size:12px; color:var(--muted); }}
  footer code {{ background:var(--surface); padding:1px 4px; border-radius:3px; font-size:11px; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
</style></head><body>

<header>
  <h1>LLM Token 定价趋势 <span class="pill">v0.3 · 中文版</span></h1>
  <div class="sub">区间 {date_min} → {date_max} · 生成时间 {today} · 来源:BerriAI/litellm git 历史 · 腾讯云文档 · fal.ai</div>
</header>

<div class="cards">
  <div class="card"><div class="label">追踪模型数</div><div class="val">{n_models}</div></div>
  <div class="card"><div class="label">价格观察点</div><div class="val">{n_obs}</div></div>
  <div class="card"><div class="label">区间内调价次数</div><div class="val">{len(changes)}</div></div>
  <div class="card"><div class="label">覆盖天数</div><div class="val" style="font-size:18px">{days} 天</div></div>
</div>

<section>
  <h2>① 区间内价格变动一览</h2>
  {chg_block}
</section>

<section>
  <h2>② 价格趋势图(按 token 计费的文本模型)</h2>
  <div class="chart-grid">
    <div class="chart-card"><h3>输入价 (Input)</h3>{fig_in}</div>
    <div class="chart-card"><h3>输出价 (Output)</h3>{fig_out}</div>
    <div class="chart-card">
      <h3>缓存价 (Cache)</h3>
      <div class="hint">实线 = 缓存读取 (cache read) · 虚线 = 缓存写入 (cache write)</div>
      {fig_cache}
    </div>
    <div class="chart-card">
      <h3>Batch API 价</h3>
      <div class="hint">实线 = Batch 输入 · 虚线 = Batch 输出 (异步,通常 50% off)</div>
      {fig_batch}
    </div>
  </div>
</section>

<section>
  <h2>③ 字段说明</h2>
  <div class="glossary"><table>{glossary_rows}</table></div>
</section>

<section>
  <h2>④ 当前价格全表 (美元 / 100 万 token)</h2>
  {table_html}
</section>

<section>
  <h2>⑤ 视频生成模型 (按秒/按视频计费)</h2>
  <div class="hint" style="font-size:12px;color:#6b7280;margin-bottom:8px;">
    "归一价 / 10 秒"列将不同计费单位折算成 10 秒标准视频的等价费用,方便横向比较;
    跨单位有近似(per_million_video_tokens 不参与折算)。
  </div>
  {media_html or '<div class="empty">尚未导入视频模型数据。</div>'}
</section>

<section>
  <h2>⑦ 跨源价格对比 (litellm vs OpenRouter vs DataLearner)</h2>
  <div class="hint" style="font-size:12px;color:#6b7280;margin-bottom:8px;">
    每个 source 的"当前最新价"对照。<b style="color:var(--up)">红色行</b> = 背离 &gt; 25%(高度可疑,通常 litellm 滞后);
    <b style="color:#a16207">黄色行</b> = 5-25% 偏离(可能厂商已降价或不同 routing);
    白色行 = 5% 内一致(可信)。OR={n_or} 行 · DL={n_dl} 行已入库。
  </div>
  {crosscheck_html}
</section>

<section>
  <h2>⑥ 数据来源与更新机制</h2>
  <table class="data-table"><thead><tr>
    <th>数据类型</th><th>来源</th><th>更新方式</th><th>下次刷新会变吗</th>
  </tr></thead><tbody>
    <tr><td>文本模型历史趋势</td>
        <td><a href="https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json" target="_blank">BerriAI/litellm</a> 周度 git 快照</td>
        <td>litellm 社区维护(调价后约 1-7 天同步)</td>
        <td><b style="color:var(--down)">是</b> · 每次跑都从 GitHub 拉新 commits</td></tr>
    <tr><td>腾讯混元</td>
        <td><a href="https://cloud.tencent.com/document/product/1729/97731" target="_blank">腾讯云文档</a> 自动抓取 + ¥7.20/USD 折算</td>
        <td><code>fetch_hunyuan.py</code> (每日 04:30)</td>
        <td><b style="color:var(--down)">是</b> · 自动追踪 6 个旗舰</td></tr>
    <tr><td>视频生成模型</td>
        <td><a href="https://fal.ai" target="_blank">fal.ai</a> 公开定价页</td>
        <td>手工录入 <code>seed_media.csv</code></td>
        <td><b style="color:var(--up)">否</b> · 需手工更新</td></tr>
  </tbody></table>
  <p class="muted" style="font-size:12px;margin-top:8px;">
    <b>延迟链:</b>厂商调价 → litellm PR (D+1~7 天) → 本脚本下次跑 (D+1~14 天)。
    设定 LaunchAgent 每天定时跑可压缩到最差 D+8 天。
  </p>
</section>

<footer>
  数据主源:<code>BerriAI/litellm/model_prices_and_context_window.json</code> 周度 git 快照。
  腾讯混元数据来自腾讯云文档(汇率按 ¥7.20/美元 换算,近似值)。
  视频模型数据来自 fal.ai 公开定价。
  豆包(Doubao)聊天模型暂缺 — 火山引擎页面为 JS 渲染,需手工填入 <code>seed_manual.csv</code>。
  Runway Gen-4 Turbo 单价未抓取到,需手工核对。<br/>
  所有价格随时可能调整,正式引用前请核对官方页。
</footer>

</body></html>
"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{today}_llm_pricing.html"
    out_path.write_text(html)
    size_kb = out_path.stat().st_size // 1024
    print(f"[report] 已生成 {out_path}  ({size_kb} KB)")
    print(f"[report] 打开:file://{out_path}")


if __name__ == "__main__":
    sys.exit(main())

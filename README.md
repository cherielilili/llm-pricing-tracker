# LLM Pricing Tracker

> 📊 **每日自动跑** · 多源交叉验证 · 自包含 HTML 报告

每日抓取主流大模型的 API token 定价，跨源交叉验证，输出可分享的 HTML 趋势报告。

🌐 **最新报告**：https://cherielilili.github.io/llm-pricing-tracker/

## 为什么做这个

单一数据源的定价数据经常滞后或有偏差：
- **litellm** 社区维护，调价后 1-7 天才同步
- **OpenRouter** 实时但有 routing 加价（5% 内）
- **DataLearner** 中文聚合，覆盖更新模型但需要爬

混合三源交叉，能在 24h 内捕捉到调价，并自动 flag 异常分歧。

## 数据源

| 源 | 类型 | 历史 | 更新延迟 |
|---|---|---|---|
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | git history (周快照) | ✅ 自 2026-01 | 1-7 天 |
| [OpenRouter](https://openrouter.ai/api/v1/models) | JSON API (当日 snapshot) | 自我累积 | 实时 |
| [DataLearner](https://www.datalearner.com/ai-models/api-prices) | HTML 表 (当日 snapshot) | 自我累积 | 实时 |
| 腾讯混元 | 手工录入 (来源:腾讯云文档) | ❌ | 手工 |
| 视频生成 (Sora/Veo/Kling/Seedance) | 手工录入 (来源:fal.ai 等) | ❌ | 手工 |

## 用法

### 在线看
直接打开 https://cherielilili.github.io/llm-pricing-tracker/

### 本地跑
```bash
git clone https://github.com/cherielilili/llm-pricing-tracker.git
cd llm-pricing-tracker
pip install pandas plotly

# 一键跑：增量 fetch + 出 HTML
./runner.sh
open reports/$(date +%Y-%m-%d)_llm_pricing.html

# 仅刷历史 (会调 GitHub API,有 60 req/h 限流)
python3 scripts/llm_pricing_backfill.py
```

## 自动化

我自己的部署：Mac Mini 上 LaunchAgent 每天 04:30 (Shanghai Time) 跑 `runner.sh`，自动 commit + push 到本仓库，触发 GitHub Pages 重建。

## 文件结构

```
llm-pricing-tracker/
├── scripts/
│   ├── llm_pricing_backfill.py  # 从 litellm git 拉历史
│   ├── llm_pricing_fetch.py     # OpenRouter + DataLearner 当日抓
│   └── llm_pricing_report.py    # 出 HTML
├── data/
│   ├── history.csv              # 长表,所有源所有时间点
│   ├── seed_manual.csv          # 手工录入文本模型 (混元等)
│   └── seed_media.csv           # 视频生成模型
├── reports/
│   └── YYYY-MM-DD_llm_pricing.html
├── index.html                   # GitHub Pages 入口 (= 最新报告)
└── runner.sh
```

## ⚠️ 免责声明

- 本仓库是公开定价数据的**自动化镜像**，不构成任何商业建议
- 数据可能滞后于厂商官方页面，**正式引用前请核对官方**
- 跨源价格分歧仅供参考，非"价格错误"判定
- 价格单位统一为 **USD / 1M tokens** (¥ 价按 ¥7.20/USD 折算，仅作示意)
- No warranty. See `data/history.csv` `source` column for provenance.

## License

数据：CC0（本身是公开信息）。脚本：MIT。

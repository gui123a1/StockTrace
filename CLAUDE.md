# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

StockTrace is a personal A-share (中国 A 股) watchlist dashboard: Django REST API + Vue 3 SPA + SQLite. Deployed **manually** on a small **1H2G** VPS (Nginx + Gunicorn + systemd + Cloudflare Flexible SSL + HTTP Basic Auth).

**Canonical code:** `backend/` and `frontend/`.  
**Deploy templates:** root `deploy/` (nginx / systemd / gunicorn / env example + `DEPLOY.md`).  
**Releases:** annotated git tags (`vX.Y.Z`) on main — no directory snapshots. Local `StockTrace v*/` folders are legacy archives, git-ignored.  
Handoff: prefer `handoff_cn.md`. `地址.md` may contain credentials — do not put secrets in a public remote.

## Commands

```bash
# Backend (from repo root)
source venv/Scripts/activate   # Windows Git Bash; PowerShell: venv\Scripts\Activate.ps1
cd backend
python manage.py runserver 8000
python manage.py migrate
python manage.py fetch_stock_data --all
python manage.py fetch_stock_data 000001 --days 5
python manage.py validate_market_sources  # read-only upstream field/source audit
python manage.py test stocks              # market service and API contract tests
python -m ruff check .                    # lint (config: backend/ruff.toml; dev dep, see requirements-dev.txt)

# Frontend
cd frontend
npm install
npm run dev      # http://localhost:5173 — proxies /api → localhost:8000
npm run build    # → frontend/dist (Nginx root on VPS)
npm run lint     # eslint (flat config; vue essential 档，不做模板风格化)
```

Linters: backend 用 `ruff`（仅 E4/E7/E9/F，抓真实错误不做风格化）；frontend 用
`eslint`（核心推荐 + vue essential）。两者都刻意不含风格化规则，避免大面积
格式 diff；Prettier 仅提供 `npm run format` 供按需使用，未做全量重排。

## Architecture

```
Browser (Vue 3 SPA, history mode)
  → /api/*  (Vite proxy in dev; Nginx reverse proxy in prod)
Django DRF (AllowAny; no CSRF — access control is Nginx Basic Auth)
  → SQLite: Stock | DailyQuote | MinuteBar
  → stocks.services: multi-source fetch (EastMoney → Sina → BaoStock → Tencent)
  → stocks.tasks: daemon-thread background fetch + in-process status
  → APScheduler (file-locked single instance): 08:50 incremental daily; 5 min 09–14 intraday; 15:10 daily summary; 15:30–21:00 every 30 min post-close lagging market cache warm (trading days only)
```

| Layer | Paths to touch first |
|-------|----------------------|
| Models | `backend/stocks/models.py` |
| Market data / search | `backend/stocks/services.py` |
| Background fetch | `backend/stocks/tasks.py` |
| REST + dashboard | `backend/stocks/views.py`, `urls.py`, `serializers.py` |
| Scheduler | `backend/stocks/apps.py`, `scheduler.py` |
| Frontend API | `frontend/src/api/stocks.js` |
| Pages / charts | `frontend/src/views/*`, `components/KlineChart.vue`, `IntradayChart.vue` |
| Format helpers | `frontend/src/utils/format.js` |
| Market hub + modules | `backend/stocks/market/`（包：`_cache`/`_sources`/`_query` 共享层 + `indices`/`flows`/`sectors`/`etf`/`institutions`/`overview` 各域模块，`__init__` 保持统一导入面）; routes under `/api/market/`; pages `/market`, `/market/trend|sectors|institutions|national-etf|etf-radar`. Source cooldown + multi-source failover for external market APIs. |

### Market Hub Phase 1

- ETF radar: `GET /api/market/etf-radar/` accepts `scope`, `rank`, `sort`,
  `order`, `q`, `min_turnover`, `page`, and `page_size` (maximum 100).
  `scope=equity_broad` is a visible research rule, not an official fund
  classification; `scope=all` always retains the complete upstream result.
- ETF detail: `GET /api/market/etfs/<six-digit-code>/?range=1m|3m|6m|1y`.
  It fetches history only for the selected ETF and returns a usable current
  snapshot when the history source is unavailable.
- Sector rotation is a current-day cross-sectional view. The 5/10/20-day
  rotation metrics are intentionally unavailable until daily snapshots are
  collected; do not infer or fabricate them from current data.
- National ETF is a maintained research watchlist, not an official holding
  disclosure. Do not add holder, weight, or entity-attribution fields without
  an auditable primary disclosure source.
- Market responses expose `meta` (`available`, `source`, `source_data_date`,
  `data_as_of`, `fetched_at`, `cache_status`, `disclaimer`). Unknown values remain `null`,
  never `0`. `data_as_of` = 最近已完成交易日（当日横截面数据的归属日）。
- Cache freshness is trading-calendar aware (`market._cache._is_fresh`): within
  TTL → fresh; beyond TTL, an entry already covering the last completed session
  close (15:00) stays fresh outside the trading-day 09:15–21:00 window — no
  upstream refetch on weekends/holidays/pre-market. Calendar is skipped under
  `manage.py test`.
- Index trend: `GET /api/market/trend/?days=30|60|120|250`（默认 120）。
- National-team flow: `GET /api/market/national-etf/flow/?period=1w|1m|3m|ytd`
  聚合 18 只观察 ETF 的历史每日主力净流入（`market/etf_flow.py`，原生
  requests 直连 push2his，https 退避重试 + http 兜底——本机/代理对东财
  TLS 有间歇性干扰，故意不走 akshare）。上游深度仅约 120 个交易日，
  超出区间如实标注 coverage_start；整包结果只在 18 只全部拉齐时缓存，
  部分失败由单只缓存渐进收敛；线路上游不可达时探针快速失败。

### Product rules

- **UI change metrics are open-relative:** `open_close_pct` / `open_close_diff`. Prev-close fields are stored, not emphasized in UI.
- **Add watchlist is fast:** create/reactivate returns immediately; backend starts **light** background fetch (name + incremental daily + ~2 trading days minutes).
- **Fetch is async:** `POST .../fetch/` and `fetch-all` return `{ status: 'started' }` (409 if busy). Poll `GET /api/stocks/fetch-status/`.
- **Intraday extrema:** window 20, min swing = 1% of day range (`IntradayChart.vue`).

### 1H2G performance constraints

- Gunicorn: **1 worker**, 2 threads (`backend/gunicorn_config.py`). Do not raise workers without RAM headroom.
- Dashboard: batched latest-quote query (no N+1).
- Daily fetch: 60-day incremental if history exists; else ~365 days.
- Name lookup prefers BaoStock/Sina over EastMoney full-market snapshot.
- Trade calendar and A-share list are cached in process memory.
- Frontend dashboard poll **60s**; keep watchlist small (≤ ~20) on VPS.

### Deploy

- App: `/opt/stocktrace` · Env: `/etc/stocktrace/env`
- systemd `User=www` — **never set `user=` in Gunicorn**
- Templates + steps: `deploy/`（根目录）
- `STATIC_ROOT` hard-coded `/opt/stocktrace/staticfiles`
- 发版 = git 标签：验证通过后在 main 上
  `git tag -a vX.Y.Z -m "说明"`，推送用 `git push --follow-tags`。
  不再维护目录快照（本地 `StockTrace v*/` 仅为历史归档，已忽略）。

## Scheduler

- `StocksConfig.ready()` → `scheduler.start()` unless `STOCKTRACE_SCHEDULER=0` or argv is a management command (`migrate`, `shell`, …).
- **File lock** `backend/scheduler.lock` so only one process runs jobs under multi-worker (still prefer 1 worker on 1H2G).
- runserver: only child with `RUN_MAIN=true` starts (avoids double start with reloader).
- Jobs: **08:50** incremental daily (trading days); **09–14 every 5 min** minutes; **15:10** daily summary (last auto write of watchlist bars); **15:30–21:00 every 30 min** post-close lagging warm (北向 / 大盘资金历史 / ETF 份额雷达 — trading days only; hard stop 21:00). No non-trading-day auto jobs; long-holiday gaps rely on next **08:50** + light-on-add + manual fetch.
- Daily fetch start = last bar − few days (or ~365d bootstrap if empty). Manual `POST .../fetch/` and `fetch-all` default **light**; pass `full=1` for fuller minute history.

## Data fetch notes

- `fetch_stock_all_data(..., light=True)` for auto-fetch after add; full path for manual refresh.
- Minute history still capped (~5 trading days max on full fetch).
- BaoStock minutes are **5-minute** bars.
- Soft-delete: `is_active=False`; re-add reactivates same `code`.

## Verification

```bash
# Backend: the scheduler is skipped for Django tests.
cd backend
python manage.py test stocks

# Frontend production bundle + lint.
cd frontend
npm run lint
npm run build
```

For a manual upstream audit, run `python manage.py validate_market_sources`.
It does not write the database or warm caches. External source failures should
be reported as unavailable/stale data, not converted into synthetic values.

## Progress records

Maintain `PROJECT_PROGRESS.md` when a planned unit is completed. Record the
date, scope, verification command or manual check, and any external blocker.
Do not mark an item complete before its relevant verification has passed.

## Frontend conventions

- Axios `baseURL: '/api'`. Use `res.data.results || res.data` for paginated lists.
- A-share colors: up `#e94560`, down `#00c853`.
- No Pinia/Vuex.

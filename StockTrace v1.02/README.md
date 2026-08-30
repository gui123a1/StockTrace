# StockTrace v1.02

手动部署用的发布快照（2026-07）。开发请以仓库根目录 `backend/`、`frontend/` 为准；本目录是发布物。

## 本版内容

| 类别 | 说明 |
|------|------|
| 文档 | 根目录 / 本包 `CLAUDE.md`；`deploy/DEPLOY.md` |
| Bug | 涨跌价格式、K 线成交量、详情换股、Gunicorn 调度锁 |
| 迭代 | 后台异步拉数 + 状态接口、添加后自动轻量拉行情、format 工具 |
| 性能 (1H2G) | Dashboard 查询合并、日线增量、light 拉取、日历缓存、1 worker、轮询降频 |
| **市场数据（一级「数据」）** | 首页：主要指数 + 北向/涨跌家数 + 概念摘要 + 主力净流入 |
| **二级专题页** | 全市场走势 · 板块资金轮动 · **机构持仓** · 国家队相关 ETF 观察 · ETF 份额雷达 |
| **多源容错** | 市场外网接口：源冷却 + 顺序 failover（非多机 LB）；主力资金历史东财失败可降级北向序列 |

### 市场路由（前端 SPA）

| 路径 | 说明 |
|------|------|
| `/market` | 数据首页 + 专题入口卡片 |
| `/market/trend` | 多指数归一化走势对比 |
| `/market/sectors` | 行业 / 概念资金轮动 |
| `/market/institutions` | 机构持仓（按股/按机构/北向/个股明细） |
| `/market/national-etf` | 国家队相关 ETF 观察（研究名单，非官方持仓） |
| `/market/etf-radar` | 份额规模、主力流入流出、涨跌榜 |

### 市场 API

| 方法 | 路径 |
|------|------|
| GET | `/api/market/` |
| GET | `/api/market/trend/` |
| GET | `/api/market/sectors/` |
| GET | `/api/market/institutions/`（可选 `?code=600519`） |
| GET | `/api/market/national-etf/` |
| GET | `/api/market/etf-radar/` |
| GET | `/api/market/etfs/<code>/?range=1m|3m|6m|1y` |

### 行情中心一期边界

- ETF 雷达支持研究规则范围与全市场范围、搜索、排序、分页和最低成交额筛选；研究规则不是基金公司的官方分类。
- 单只 ETF 详情仅按需拉取所选标的的价格历史。历史源失败时保留当前快照，并明确显示历史不可用。
- 板块资金是当日横截面强弱，不代表板块之间真实资金路径；5/10/20 日轮动要等日度快照积累后再开放。
- 国家队相关 ETF 页面是维护的观察名单，不提供无可审计来源的真实持仓、权重或机构归属。
- API 统一返回来源、源数据日期、抓取时间、缓存状态和免责声明；未知字段返回 `null`，不伪装为 `0`。

### 发布前验证

```bash
cd backend
python manage.py test stocks
python manage.py validate_market_sources  # 只读上游校验；需要外网

cd ../frontend
npm run build
```

`validate_market_sources` 不写数据库、不修改缓存。外部源被代理或限流阻断时，应保留降级状态并记录原因。

实现：`backend/stocks/market.py`（进程内缓存 + 源冷却，避免 1H2G 打爆外网）。机构数据为公开季报/股东披露，**有滞后**。

Nginx 需保持 SPA `try_files $uri $uri/ /index.html`，否则刷新二级路径会 404。

## 目录

```
StockTrace v1.02/
├── CLAUDE.md
├── README.md
├── .gitignore
├── backend/           # Django + gunicorn_config.py
├── frontend/          # Vue 源码（VPS 上 npm run build）
└── deploy/
    ├── DEPLOY.md
    ├── env.example
    ├── nginx-stocktrace.conf
    └── stocktrace.service
```

## 快速升级（已有 `/opt/stocktrace`）

见 [deploy/DEPLOY.md](deploy/DEPLOY.md)。

**务必：**

1. 同步本包 `backend/`、`frontend/` 源码到 VPS  
2. 前端 `npm install && npm run build`  
3. 后端 `migrate`（本批市场页无新迁移，可跳过）+ `systemctl restart stocktrace`  
4. 浏览器强刷；点「数据」进入二级页验证  

无新 Python 依赖（仍用已有 `akshare`）。

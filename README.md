# StockTrace

个人用 A 股自选股监控面板 + 行情中心。后端 Django REST + SQLite，前端 Vue 3 + ECharts，部署在一台 1H2G 的小 VPS 上（Nginx + Gunicorn + systemd + Cloudflare，访问控制走 Nginx HTTP Basic Auth）。

## 功能

**自选监控**

- 按代码/名称搜索添加关注，添加即后台轻量拉取（不阻塞）
- 可折叠表格：实时价格、相对开盘的涨跌（`open_close_pct` 口径）
- 日 K 蜡烛图 + 当日分钟走势（局部极值检测，1% 振幅阈值），点击 K 线柱切换对应日期走势

**行情中心（`/market`）**

| 路径 | 说明 |
|------|------|
| `/market` | 数据首页：主要指数 + 宽基估值分位 + 北向/涨跌家数 + 涨停池情绪 + 两融余额 + 概念摘要 + 主力净流入 |
| `/market/trend` | 多指数归一化走势对比 |
| `/market/sectors` | 行业/概念板块资金轮动（当日横截面） |
| `/market/institutions` | 机构持仓（按股/按机构/北向/个股明细，可选 `?code=`） |
| `/market/national-etf` | 国家队相关 ETF 观察（研究名单，非官方持仓） |
| `/market/etf-radar` | ETF 份额规模、主力流入流出、涨跌榜 |

**探测器（`/detector`）**

主动分析型模块：在成交量处于相对平稳区间（平静判定：量比 0.7~1.5、量能波动收窄、振幅低位）时，监测「量比斜率 / 大单净流入 / 波动率压缩 / 换手率分位 / 融资余额 / 价格与均线关系」等维度的渐进变化；至少 2 个维度同向、连续维持 2 个周期以上、幅度温和才产出信号（分级 高/中/低）。每交易日 17:15 自动扫描，并回看 5 个交易日信号的命中率，自动微调维度权重与投票门槛（有界、全程留痕）。页面含信号列表（按严重程度筛选）、信号详情（各维度曲线）与板块微变热力图。

**维度口径与已知边界**（数据诚信红线，不做合成数值）：

- 「换手率分位」以成交量自身 60 日分位实现：个股窗口内流通股本基本不变，与换手率分位单调等价；指数无股本概念，为活跃度代理。
- 「融资余额/北向」仅融资余额口径（北向自 2024-08 停止逐日净买额披露）；融资余额为交易所 T+1 披露、经本站日度快照积累，上线初期约需一周凑齐窗口。
- 「委比与挂单结构」「板块内分化」两维度因无数据源**暂未启用**（前者需 Level-1 盘口数据，后者需板块成分股横截面，现有日度快照仅含板块净额与涨跌幅）；启用状态与原因在页面「维度与迭代状态」与 `/api/detector/config/` 中可见，待数据源接入后开启。
- 上游/快照不足的对象当天跳过并记录降级原因（`/api/detector/` 各响应 `meta` 与扫描日志），绝不伪造信号。

行情 API 统一返回 `meta`（来源、源数据日期、抓取时间、缓存状态、免责声明）；未知字段返回 `null`，不伪装为 `0`。

## 数据边界

- 板块资金是当日聚合强弱指标，不代表板块之间真实资金转移路径；当日横截面来自同花顺（东财板块接口对境外不可用），5/10 日有东财原生排行兜底，20 日轮动由日度快照积累供数（2026-09 起积累中）。
- ETF 雷达的「股票/宽基范围」是可审计的名称规则筛选，不是基金官方分类；单只 ETF 详情只按需拉取价格历史，历史源失败时保留当前快照并明确提示。
- 国家队 ETF 页面是维护的研究观察名单，不提供无可审计来源的持仓主体、权重或成本。
- 机构数据来自公开季报/股东披露与北向统计，有披露滞后。
- 外部源失败一律报 unavailable/stale 并降级到下一源（源冷却 + 顺序 failover），绝不合成数值。

## 开发

```bash
# 后端（仓库根目录，Windows Git Bash）
source venv/Scripts/activate
cd backend
python manage.py migrate
python manage.py runserver 8000
python manage.py test stocks        # 市场服务与 API 契约测试

# 前端
cd frontend
npm install
npm run dev      # http://localhost:5173，/api 代理到 8000
npm run lint && npm run build
```

目录速览：`backend/stocks/`（models / services 多源抓取 / tasks 后台拉取 / market/ 行情中心包 / detector/ 探测器包 / scheduler 定时任务）；`frontend/src/`（views / components / api）；`deploy/`（VPS 部署模板与 `DEPLOY.md`）。

定时任务（APScheduler，交易日才跑）：08:50 盘前增量日线；09–14 点每 5 分钟分钟线；15:10 收盘汇总；15:30–21:00 每 30 分钟预热晚到行情缓存；17:15 探测器日度扫描（可 `python manage.py run_detector_scan` 手动触发）。

## 部署

1H2G VPS：Nginx + Gunicorn（1 worker 2 线程）+ systemd，Cloudflare Full (strict) SSL + Nginx 限流 + Basic Auth。模板与步骤见 [`deploy/DEPLOY.md`](deploy/DEPLOY.md)。发版流程：验证通过后在 main 上打注释标签 `git tag -a vX.Y.Z` 并 `git push --follow-tags`。

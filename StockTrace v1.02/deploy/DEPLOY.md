# StockTrace v1.02 部署说明

目标环境：Ubuntu 22.04，**1H2G** VPS，路径 `/opt/stocktrace`，Nginx + Gunicorn + systemd，Cloudflare Flexible SSL，HTTP Basic Auth。

本目录为**发布快照**（与仓库根目录 `backend/`、`frontend/` 同步的一份拷贝）。日常开发改根目录；部署时把本快照或 git 同步到 VPS。

---

## 0. 相对 v1.01 / 线上旧版的变更

### Bug

- 看板「涨跌价」不再误加 `%`
- 日 K 成交量柱（注册 ECharts `BarChart`）
- 详情路由换 `id` 会重新加载
- Gunicorn 下 APScheduler：文件锁单实例 + 不再只靠 `RUN_MAIN`

### 功能

- 拉取改为**后台线程**，接口立即返回；`GET /api/stocks/fetch-status/` 可轮询
- 添加/恢复自选后**自动轻量拉行情**（补名称 + 增量日线 + 近 2 日分钟）
- 前端 `utils/format.js` 统一格式化
- **市场数据一级页「数据」** + 二级专题（需前端重新 build，Nginx 已配置 SPA `try_files`）：
  - `/market` 首页（指数 + 北向/情绪摘要）
  - `/market/trend` 全市场走势
  - `/market/sectors` 板块资金轮动
  - `/market/institutions` 机构持仓（季报/股东变动/北向；`?code=` 个股明细）
  - `/market/national-etf` 国家队相关 ETF 观察（研究名单，非官方持仓）
  - `/market/etf-radar` ETF 份额雷达
  - API：`GET /api/market/`、`/api/market/trend|sectors|institutions|national-etf|etf-radar/`
  - 单只 ETF：`GET /api/market/etfs/<code>/?range=1m|3m|6m|1y`
- 市场外网：源冷却 + 多源 failover（主力资金历史可降级北向序列）

### 1H2G 性能

- Dashboard **2 次查询**拼最新行情（去掉 N+1）
- 日线按「最近一根 bar + 重叠」增量；无历史才 bootstrap ~365 天
- 添加后 / 手动刷新默认 **light**（少分钟）；`full=1` 才更全
- 调度：**08:50** 增量日线 · **09–14 */5** 分钟 · **15:10** 收盘 · **15:30–21:00 */30** 晚到行情缓存预热（仅交易日，不写新的市场历史表）
- 交易日日历 / A 股列表缓存；名称优先 BaoStock/新浪（避免东财全市场快照）
- Gunicorn 默认 **1 worker × 2 threads**（`gunicorn_config.py`）
- 看板轮询 **60s**；拉取状态轮询 3s
- 详情页用 `GET /stocks/:id/` 不再拉整表

---

## 1. 首次部署（概要）

```bash
# 系统依赖（示例）
sudo apt update
sudo apt install -y python3.12 python3.12-venv nginx apache2-utils

# 代码放到 /opt/stocktrace （本快照的 backend + frontend）
sudo mkdir -p /opt/stocktrace /etc/stocktrace /opt/stocktrace/staticfiles
sudo chown -R www:www /opt/stocktrace

# 虚拟环境
cd /opt/stocktrace
python3.12 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
pip install gunicorn

# 环境变量
sudo cp deploy/env.example /etc/stocktrace/env
sudo nano /etc/stocktrace/env   # 填 SECRET_KEY、ALLOWED_HOSTS

# 数据库
cd /opt/stocktrace/backend
source ../venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput

# 前端构建（需 Node >= 20）
cd /opt/stocktrace/frontend
npm ci
npm run build

# systemd
sudo cp deploy/stocktrace.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stocktrace

# Nginx + Basic Auth
sudo htpasswd -c /etc/nginx/.htpasswd_stocktrace stocktrace
sudo cp deploy/nginx-stocktrace.conf /etc/nginx/sites-available/stocktrace
sudo ln -sf /etc/nginx/sites-available/stocktrace /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

注意：

- **Gunicorn 配置不要设 `user=`**，systemd 已是 `User=www`
- Cloudflare SSL 模式：Flexible
- 域名改到你自己的 `server_name`

---

## 2. 从旧版升级到 v1.02

```bash
# 备份
sudo systemctl stop stocktrace
cp /opt/stocktrace/backend/db.sqlite3 /opt/stocktrace/backend/db.sqlite3.bak.$(date +%Y%m%d)

# 同步代码（按你习惯：scp / git / tar）
# 保证 gunicorn_config.py、stocks/tasks.py、scheduler.py 等到位

cd /opt/stocktrace
source venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python manage.py test stocks
python manage.py migrate
python manage.py collectstatic --noinput

cd /opt/stocktrace/frontend
npm ci && npm run build

# 若尚未使用本仓库 gunicorn_config，更新 systemd ExecStart 指向它
sudo cp /path/to/StockTrace\ v1.02/deploy/stocktrace.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start stocktrace

# 确认调度只启动一次
sudo journalctl -u stocktrace -n 50 --no-pager | grep -i APScheduler
```

期望日志：`APScheduler 已启动` 出现一次；其它 worker 日志可有「其他进程已持有调度锁」（单 worker 时通常只有启动成功）。

---

## 3. 运维命令

```bash
sudo systemctl status stocktrace
sudo systemctl restart stocktrace
sudo journalctl -u stocktrace -f

# 手动拉数（在 venv 内）
cd /opt/stocktrace/backend
python manage.py fetch_stock_data --all

# 只读校验 ETF/板块上游字段与单位；不写数据库、不修改缓存
python manage.py validate_market_sources

# 临时关闭调度
# 在 /etc/stocktrace/env 加：STOCKTRACE_SCHEDULER=0 后 restart
```

---

## 4. 低配建议

| 项 | 建议 |
|----|------|
| 自选数量 | 尽量 ≤ 20，盘中任务按股串行 |
| Gunicorn workers | 保持 1；内存仍紧再降 threads |
| 勿在 VPS 上 `npm run dev` | 只用 `dist` |
| 勿提交 | `db.sqlite3`、`.env`、htpasswd、真实 SECRET_KEY |

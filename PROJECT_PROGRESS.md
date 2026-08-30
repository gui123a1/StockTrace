# StockTrace 项目进度

最后更新：2026-08-30

本文件记录已经完成并经过验证的工作。实现完成但尚未验证的事项保持“进行中”，不得提前标记完成。

## 当前状态

| 状态 | 工作项 | 说明 |
|---|---|---|
| 已完成 | 行情中心一期实现 | ETF 雷达、单只 ETF 详情、板块资金工作台、国家队相关 ETF 观察页及统一数据状态 |
| 已完成 | 行情中心一期浏览器验收 | 三个页面桌面端与 375px 移动端流程已验收；宽表支持横向滚动 |
| 已完成 | 发布范围审计 | 确认需要同步的 14 个源码文件，并排除数据库、密钥、依赖目录、构建产物和运行锁 |
| 已完成 | 项目与发布文档同步 | 根 `CLAUDE.md`、v1.02 `README.md` 和 `deploy/DEPLOY.md` 已补齐数据边界与验证命令 |
| 已完成 | v1.02 源码快照同步 | 14 个行情中心一期源码文件与 `CLAUDE.md` 已同步，并通过 SHA256 一致性校验 |
| 已完成 | 发布前验证 | Django 市场测试和前端生产构建均已通过；v1.02 同步文件已完成 SHA256 校验 |
| 已完成 | 工程化改进（2026-08-30） | git 版本控制、ruff/eslint 静态检查、market 包拆分、板块页组件化、路由懒加载；已推送 GitHub |
| 已完成 | 发布流程切换为 git 标签 | deploy 模板移至根目录，两个快照目录退出 git（本地归档），基线提交打 `v1.2.0` 标签，新增根 README |
| 已完成 | 交易日历感知缓存 + 数据日期展示 + 走势时间段 | 周末/节假日不再触发上游重拉；meta 增加 `data_as_of` 并在页面展示；走势页支持 30/60/120/250 日切换 |

## 完成记录

### 2026-08-30：交易日历感知缓存 + 数据日期展示 + 走势时间段选择

- **缓存新鲜度感知交易日历**（`market/_cache._is_fresh`）：TTL 过期但缓存已覆盖最近已完成交易日收盘（15:00），且当前不在交易日 09:15–21:00 数据变化窗口内，视为新鲜——周末/节假日/盘前不再触发上游 40 秒级重拉；`manage.py test` 下日历逻辑停用以保持确定性。动机：用户反馈周末打开国家队 ETF 页要等约 40–95 秒。
- **数据归属日期展示**：`meta` 新增 `data_as_of`（最近已完成交易日）；状态栏组件与板块页头部显示"数据截至"，板块页误导性的"当日快照"徽标改为真实日期。
- **走势时间段选择**：`GET /api/market/trend/` 支持 `?days=30|60|120|250`（校验 + 400 测试）；走势页新增时间段按钮。
- 边界说明：板块 5/10/20 日、ETF 份额 1/5/20 日变化仍需日度快照积累（下一阶段），未做任何伪造。
- 验证：`manage.py test stocks` 19 通过、ruff/eslint/build 通过；浏览器实测国家队页日期展示、走势 30/60/120/250 切换；缓存写入 12 分钟后（TTL 4 倍）请求仍 0.2 秒命中。

### 2026-08-30：工程化改进（版本控制 / 拆分 / lint / 包体积）

- **git 版本控制**：根目录 `git init`（分支 main），新增根 `.gitignore`（排除 venv、node_modules、dist、数据库、调度锁、`.env` 与含凭据的 `地址.md`），以现有代码建立基线提交。
- **后端 lint**：接入 ruff（`backend/ruff.toml`，仅 E4/E7/E9/F）+ `requirements-dev.txt`；修复 9 处未用导入/死代码。验证：`ruff check` 全绿，16 个 Django 测试通过。
- **market 模块拆分**：1482 行 `market.py` 拆为 `stocks/market/` 包（`_cache`/`_sources`/`_query` 共享层 + indices/flows/sectors/etf/institutions/overview 六个域模块），包 `__init__` 保持原导入面，views/scheduler/validate 命令零改动；测试桩路径改指 `stocks.market.etf.*`；删除从未调用的 `_try_source_fns`。验证：`manage.py test stocks` 16 通过、`manage.py check` 无问题、`validate_market_sources` 实测上游正常。
- **前端路由懒加载**：除首页外全部路由改动态导入。主包 837.36 kB（gzip 284.74 kB）→ 148.61 kB（gzip 56.65 kB），echarts 拆为 481 kB 独立异步 chunk，不再触发 500 kB 警告。
- **板块资金页组件化**：1175 行 `MarketSectors.vue` 拆出 `SectorFlowStage.vue`（资金流向舞台）与 `SectorInsights.vue`（解读/强弱面板），纯展示函数抽到 `utils/sectorFlow.js`，页面降至 575 行。验证：生产构建通过；浏览器实测 1280px/375px 渲染、板块切换交互、空数据兜底均正常。
- **前端 lint**：接入 eslint 10 flat config（核心推荐 + vue essential，不做模板风格化）与 prettier 配置（仅 `npm run format`，未全量重排）；新增 `npm run lint`。修复 4 项：KlineChart computed 内副作用改为派生 computed、MarketEtfRadar 未用 watch、两个单词组件名按 views 目录豁免。
- **安全边界说明**：`settings.py` DRF 段写明 AllowAny + 无 CSRF 依赖 Nginx Basic Auth 的三条红线。
### 2026-08-30：发布流程切换为 git 标签，快照目录退役

- `StockTrace v1.02/deploy/` 上移为根目录 `deploy/`（nginx / systemd / gunicorn / env 示例 + `DEPLOY.md`）。
- `StockTrace v1.01/`、`StockTrace v1.02/` 执行 `git rm -r --cached` 退出版本库（本地文件保留归档），`.gitignore` 增加 `StockTrace v*/`。
- 基线提交 `390c308` 打注释标签 `v1.02`（其内容即 v1.02 发布状态，唯一差异为 MarketSectors.vue 的格式重排）；今后发版 = 验证通过后在 main 上打 `vX.Y.Z` 标签并 `git push --follow-tags`。
- 基线标签规范化：`v1.02` 已重命名为 `v1.2.0`（同一提交 `390c308`，标签说明原文保留并注明改名），对齐 SemVer 三段式；今后版本从 `v1.2.x` / `v1.3.0` 接续升版。
- 新增根 `README.md`（面向公开仓库的项目说明，改写自 v1.02 发布说明，保留功能清单、路由/API 与数据边界）。
- 推送前全量审计跟踪文件：无密钥、无 IP 明文（`vps-download-notes.md` 为占位符）、无数据库/锁/依赖目录；两个快照目录是唯一不应入库的内容。
- 验证：`git status` 干净、标签指向正确、`git push --follow-tags` 成功。

### 2026-08-03：发布范围审计

- 后端需同步：`market.py`、`scheduler.py`、`tests.py`、`urls.py`、`views.py`、`validate_market_sources.py`。
- 前端需同步：市场 API、两个公共组件、市场导航和四个市场页面。
- 明确排除：`db.sqlite3`、`.env`、`scheduler.lock`、`__pycache__`、`*.pyc`、`venv`、`node_modules`、`dist`、本地编辑器配置及凭据文件。

### 2026-08-03：文档同步

- `CLAUDE.md` 已记录行情中心一期 API、真实数据边界、测试命令、快照同步规则和进度维护约定。
- v1.02 发布说明已补充 ETF 详情 API、当日板块口径、观察名单语义和历史源失败时的降级行为。
- 部署说明已把旧的 21:00 保活描述更正为 15:30–21:00 每 30 分钟的晚到行情缓存预热。

### 2026-08-03：v1.02 快照同步

- 已同步 14 个审计确认的行情中心一期源码文件，以及更新后的 `CLAUDE.md`。
- 15 个同步文件的 SHA256 与权威工作树完全一致。
- 已检查快照不含数据库、密钥、运行锁或 Python 字节码。

### 2026-08-03：发布前验证

- `backend`: `python manage.py test stocks` 通过，16 个测试全部成功；Django system check 无问题。
- `frontend`: `npm run build` 通过，Vite 已生成生产包。
- 构建工具提示主 JavaScript 压缩后约 833 kB，属于后续可做的代码分割优化建议，不阻塞本次发布。

## 后续阶段（不属于本次一期收口）

- 积累 ETF 与板块日度快照后，再开放 1/5/20 日份额变化和多周期板块轮动。
- 只有取得可审计的一手披露来源后，才考虑真实机构/国家队持仓实体、权重和持仓变化。

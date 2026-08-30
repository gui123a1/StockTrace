# VPS 文件下载到本地

## 核心原则

- 小文件 / 纯代码：优先 **Git 推送 + 本地 pull**（走 HTTPS，可被 VPN 代理）
- 大文件 / 一次性备份：优先 **打包 + 通过已有 Nginx 域名下载**（走 HTTPS + Basic Auth）
- 避免直连 `scp/ssh` 跨洋拉大文件（机场常只代理浏览器流量，SSH 不一定走 VPN）

---

## 方案 A：Git 备份（代码最常用）

适合：后端/前端源码、配置文件。

```bash
# 在 VPS 上
cd /opt/stocktrace
git init
git add -A
git commit -m "vps-backup-$(date +%Y%m%d)"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
# 若远端已有历史且你确认要覆盖：
# git push -u origin main --force
```

```bash
# 在本地
cd <本地项目目录>
git pull origin main
```

注意：不要把 `venv/`、`node_modules/`、`db.sqlite3`、密钥文件提交进仓库。

---

## 方案 B：打包后通过 Nginx 域名下载（推荐大文件）

适合：整目录备份、压缩包较大、不想开额外端口。

```bash
# 在 VPS 上打包（排除环境与缓存）
cd /opt/stocktrace
tar czf /opt/stocktrace/frontend/dist/stocktrace-backup.tar.gz \
  --exclude='backend/venv' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='db.sqlite3' \
  backend/ frontend/
```

本地浏览器访问（会走 VPN，并经过 Nginx Basic Auth）：

```text
https://stocktrace.yumeat.cc.cd/stocktrace-backup.tar.gz
```

下载完成后清理：

```bash
# 在 VPS 上
rm -f /opt/stocktrace/frontend/dist/stocktrace-backup.tar.gz
```

---

## 方案 C：临时 HTTP 下载服务（不推荐长期）

适合：没有现成 Nginx 站点时临时救急。

```bash
# 在 VPS 上先打包
cd /opt/stocktrace
tar czf /tmp/stocktrace-backup.tar.gz \
  --exclude='backend/venv' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='db.sqlite3' \
  backend/ frontend/

# 临时提供下载
cd /tmp
python3 -m http.server 9999 --bind 0.0.0.0
```

本地浏览器访问：

```text
http://<VPS_IP>:9999/stocktrace-backup.tar.gz
```

用完必须关闭：

```bash
# 停止服务：在运行 http.server 的终端按 Ctrl+C
# 若已后台运行，按端口杀进程
lsof -i :9999 | grep LISTEN | awk '{print $2}' | xargs -r kill -9

# 若曾放行防火墙端口，关闭它
sudo ufw delete allow 9999/tcp

# 删除临时包
rm -f /tmp/stocktrace-backup.tar.gz
```

风险：`python -m http.server` 默认无认证，等于临时把目录暴露到公网。

---

## 方案 D：scp / rsync（直连，速度常慢）

适合：同机房、内网、或 SSH 本身很快时。

```bash
# 先在 VPS 打包
ssh root@<VPS_IP> "cd /opt/stocktrace && tar czf /tmp/stocktrace-backup.tar.gz \
  --exclude='backend/venv' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='db.sqlite3' \
  backend/ frontend/"

# 本地下载（-C 开启传输压缩）
scp -C root@<VPS_IP>:/tmp/stocktrace-backup.tar.gz ./
```

说明：
- 很多机场只代理浏览器流量，不代理 SSH，所以 scp 可能很慢
- 中断下载：终端 `Ctrl + C`

---

## 打包时建议排除

```text
backend/venv/
frontend/node_modules/
frontend/dist/
**/__pycache__/
**/*.pyc
db.sqlite3
.env
*.log
```

---

## 本地下载后解压

```bash
# Linux / macOS / Git Bash
mkdir -p vps-backup
tar xzf stocktrace-backup.tar.gz -C vps-backup
```

```powershell
# Windows PowerShell（若已装 tar）
mkdir vps-backup
tar -xzf stocktrace-backup.tar.gz -C vps-backup
```

---

## 快速决策

| 场景 | 推荐 |
|------|------|
| 只备份源码 | Git 推送 |
| 整包备份，文件较大 | Nginx 域名下载打包文件 |
| 临时救急且无站点 | 临时 HTTP，用完立刻关 |
| SSH 很快 | scp/rsync |

---

## 安全提醒

1. 不要把密钥、`.htpasswd`、数据库明文长期放公网可访问路径
2. 临时端口用完立刻关闭
3. 通过 Nginx 下载时，下载完尽快删除 `dist` 下的 tar 包
4. 强制推送 Git 前先确认不会覆盖别人需要的历史

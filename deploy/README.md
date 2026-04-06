# 部署指南

## 前置条件

- Windows 10/11 + WSL2（已启用 systemd）
- WSL 中已安装 PostgreSQL 并创建数据库
- 已获取企业微信应用凭证（CorpID / AgentId / Secret / Token / EncodingAESKey）
- 已获取 DeepSeek API Key

## WSL2 启用 systemd

编辑 `/etc/wsl.conf`：

```ini
[boot]
systemd=true
```

然后在 PowerShell 中重启 WSL：

```powershell
wsl --shutdown
wsl
```

## 一键部署

```bash
cd /home/ycm/longzhongxian
bash deploy/setup.sh
```

脚本会依次完成：
1. 检查 Python 3.11+
2. 创建 venv + 安装依赖
3. 安装 Playwright Chromium
4. 复制 `.env.example` → `.env.local`（首次需手动填入实际值后重跑）
5. 验证环境配置
6. 运行数据库迁移
7. 安装并启动 systemd 服务

## 常用命令

```bash
# 查看服务状态
sudo systemctl status longzhongxian

# 查看实时日志
journalctl -u longzhongxian -f

# 重启服务
sudo systemctl restart longzhongxian

# 停止服务
sudo systemctl stop longzhongxian
```

## Windows 开机自启

将 `deploy/start-wsl.vbs` 复制到 Windows 启动目录：

1. `Win+R` → 输入 `shell:startup` → 回车
2. 将 `start-wsl.vbs` 复制到打开的文件夹中

开机后 WSL 会自动启动，systemd 自动拉起服务。

## 内网穿透（企微回调）

企微回调需要公网可达的 URL。推荐使用 cloudflare tunnel：

```bash
# 安装 cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# 登录并创建隧道
cloudflared tunnel login
cloudflared tunnel create longzhongxian
cloudflared tunnel route dns longzhongxian your-domain.com

# 运行隧道
cloudflared tunnel --url http://localhost:8000 run longzhongxian
```

也可使用 frp 或 ngrok 作为替代方案。

## Boss 直聘浏览器

C1 抓取需要连接本地已登录的 Chrome/Edge 浏览器：

1. 用带远程调试端口的方式启动浏览器（Windows 侧）：
   ```
   chrome.exe --remote-debugging-port=9222
   ```
2. 在浏览器中登录 Boss 直聘并保持登录状态
3. C1 通过 `connect_over_cdp("http://localhost:9222")` 连接

## 目录说明

```
deploy/
  longzhongxian.service  # systemd 服务单元文件
  setup.sh               # 一键部署脚本
  start-wsl.vbs          # Windows 开机自启 WSL
  README.md              # 本文件
```

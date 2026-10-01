# Server Monitor

[English](README.md) | [繁體中文](README.zh-TW.md)

**簡單、免費、不需要在每台主機安裝監控 Agent 的 Linux / NVIDIA GPU 多伺服器監控 Dashboard。**

Server Monitor 主要為研究室、AI 團隊，以及多人共用 GPU Server 的環境所設計，讓你可以快速知道：

- 哪些 Server 現在正在使用？
- 哪些 GPU 還是空閒的？
- GPU 記憶體目前用了多少？
- 現在是誰在使用 GPU？
- 哪些 Process 正在占用 GPU？

不需要在每一台 Server 額外安裝監控 Agent，也不需要建置複雜的監控架構。Server Monitor 直接透過既有的 SSH 連線取得各台 Server 的系統資訊，並集中顯示於同一個 Web Dashboard。

## Preview

![Server Monitor Dashboard](docs/dashboard.png)

## 為什麼做 Server Monitor？

最初開發 Server Monitor，是因為我想在研究室環境中快速查看多台共用 GPU Server 的使用狀況。

現有的 Server Monitoring 工具功能通常非常完整，但對小型研究室或 AI 團隊來說，有時反而過於複雜。有些方案需要在每台 Server 安裝 Agent 或 Exporter，有些需要額外建置多個服務與設定監控架構，也有部分商業服務需要付費訂閱。

但很多時候，我真正想知道的其實很簡單：

> **這台 Server 現在有沒有人用？哪張 GPU 還有空？**

因此 Server Monitor 專注在一個簡單的使用情境：

> **只要能 SSH 進 Server，就能監控 Server。**

不需要在每台被監控主機額外安裝監控 Agent、不需要付費服務，也不需要先架設 Prometheus + Grafana。

只需要在一台主機上執行 Server Monitor，設定欲監控的 Server，即可透過瀏覽器集中查看 CPU、Memory、Disk、GPU，以及目前使用 GPU 的 User 與 Process。

## 主要特色

- **Agentless Monitoring** — 被監控的 Server 不需要額外安裝監控 Agent
- **SSH-based** — 直接使用原本就有的 SSH 連線
- **Multi-server Dashboard** — 在同一個頁面查看多台 Server
- **GPU 使用者資訊** — 查看目前是哪個 User / Process 正在占用 GPU
- **免費且開源** — 不需要訂閱商業監控服務
- **輕量部署** — 可使用 Docker Compose 或 Python 直接執行
- **不需要複雜監控架構** — 不必額外架設 Prometheus 或 Grafana

## Features

- 多台 Linux / NVIDIA GPU Server 集中監控
- CPU、Memory、Disk 即時使用狀態
- NVIDIA GPU 使用率、VRAM 與功耗
- GPU Process、PID 與 User 資訊
- 支援 SSH Key 與密碼驗證
- WebSocket 即時更新，並提供 HTTP polling fallback
- 支援 Docker Compose 快速部署
- 可搭配 Nginx、Basic Auth 與 UFW 進行遠端部署

## 運作方式

Server Monitor 只需要部署在一台主機上，再透過 SSH 向其他 Server 取得系統資訊。

```text
                     ┌─────────────────────┐
                     │   Server Monitor    │
                     │    Web Dashboard    │
                     └──────────┬──────────┘
                                │
                            SSH 連線
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
      GPU Server 01      GPU Server 02      GPU Server 03
      CPU / Memory       CPU / Memory       CPU / Memory
      Disk / GPU         Disk / GPU         Disk / GPU
      User / Process     User / Process     User / Process
```

被監控的 Server 只需要：

- 可正常使用的 SSH Server
- `free`、`df`、`ps` 等基本 Linux 指令
- 若需監控 NVIDIA GPU，可正常執行 `nvidia-smi`

被監控端不需要另外部署專用的 Monitoring Agent。

---

## Quick Start

建議優先使用 **Docker Compose**。如果要直接修改或開發 Python 程式，可使用 **venv**。

### Option A — Docker Compose（推薦）

#### 1. 建立設定檔

```bash
cp servers.example.json servers.json
```

編輯 `servers.json`，加入要監控的主機。例如使用密碼驗證：

```json
[
  {
    "name": "GPU-Server-01",
    "host": "192.168.1.101",
    "port": 22,
    "username": "student",
    "password": "your_password"
  }
]
```

> 建議正式環境改用 SSH Key 驗證，並避免將 `servers.json` 提交至 Git。

#### 2. 啟動服務

```bash
docker compose up -d --build
```

#### 3. 開啟 Dashboard

在執行 Docker 的主機開啟：

```text
http://127.0.0.1:5000
```

目前 `docker-compose.yml` 預設只綁定 `127.0.0.1:5000`，不會直接暴露至外部網路。

若需要從其他電腦存取，建議使用：

- SSH Tunnel
- Nginx Reverse Proxy

正式對外部署方式請參考後面的 [Production Deployment](#production-deploymentoptional)。

---

### Option B — Python venv

適合本機開發、測試或修改程式。

#### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp servers.example.json servers.json
python app.py
```

#### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item servers.example.json servers.json
python app.py
```

啟動後開啟：

```text
http://127.0.0.1:5000
```

---

## Server Configuration

所有監控目標皆設定於 `servers.json`。

### Password Authentication

```json
[
  {
    "name": "GPU-Server-01",
    "host": "192.168.1.101",
    "port": 22,
    "username": "student",
    "password": "your_password"
  }
]
```

### SSH Key Authentication（推薦）

先在專案根目錄建立 SSH Key：

```bash
ssh-keygen -t ed25519 -f ./monitor_key -N ""
chmod 600 monitor_key
```

將公鑰加入欲監控主機：

```bash
ssh-copy-id -i ./monitor_key.pub -p 22 student@192.168.1.101
```

#### 使用 Docker

`servers.json` 內的 `private_key` 必須填寫 **容器內路徑**：

```json
[
  {
    "name": "GPU-Server-01",
    "host": "192.168.1.101",
    "port": 22,
    "username": "student",
    "private_key": "/app/monitor_key"
  }
]
```

`docker-compose.yml` 會將專案目錄下的私鑰掛載至容器：

```yaml
volumes:
  - ./servers.json:/app/servers.json:ro
  - ./monitor_key:/app/monitor_key:ro
```

#### 使用 Python venv

如果直接在專案根目錄執行 `python app.py`，可使用本機路徑：

```json
[
  {
    "name": "GPU-Server-01",
    "host": "192.168.1.101",
    "port": 22,
    "username": "student",
    "private_key": "./monitor_key"
  }
]
```

> Docker 與 venv 使用的 SSH Key 路徑不同，請依執行方式設定。

---

## Monitor the Docker Host

若 Server Monitor 本身執行於 Docker，而你也想監控 Docker 所在的宿主機，可使用：

```json
[
  {
    "name": "Host-Local",
    "host": "host.docker.internal",
    "port": 22,
    "username": "localuser",
    "private_key": "/app/monitor_key"
  }
]
```

請確認宿主機有啟用 SSH Server，且帳號可以正常透過 SSH 登入。

---

## Requirements for Monitored Servers

被監控的 Linux 主機需具備：

- 可正常使用的 SSH Server
- 可執行 `free`、`df`、`ps` 等基本 Linux 指令
- 若要監控 NVIDIA GPU，需安裝 NVIDIA Driver 並可正常執行：

```bash
nvidia-smi
```

若沒有 NVIDIA GPU，CPU、Memory 與 Disk 監控仍可正常使用。

---

## Project Structure

```text
server-monitor/
├── app.py
├── templates/
│   └── index.html
├── servers.example.json
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .gitignore
└── README.md
```

執行時另外建立的檔案：

```text
servers.json        # 實際伺服器設定，請勿提交至 Git
monitor_key         # SSH 私鑰，請勿提交至 Git
monitor_key.pub     # SSH 公鑰
```

---

## Common Docker Commands

啟動或重新 Build：

```bash
docker compose up -d --build
```

查看 Log：

```bash
docker compose logs -f
```

修改 `servers.json` 後重新啟動：

```bash
docker compose restart
```

停止服務：

```bash
docker compose down
```

---

## Remote Access with SSH Tunnel

如果只需要自己從遠端電腦查看 Dashboard，可以不用開放 Port 5000，也不用設定 Nginx。

在自己的電腦執行：

```bash
ssh -L 5000:127.0.0.1:5000 -p <SSH_PORT> <USER>@<SERVER_IP>
```

接著瀏覽：

```text
http://127.0.0.1:5000
```

這通常是研究室或內部環境中最簡單的遠端存取方式。

---

## Production Deployment（Optional）

如果 Dashboard 需要提供給多人或長期遠端使用，建議保持 Docker 的 `127.0.0.1:5000` 綁定，並由 Nginx 提供外部入口。

### 1. Install Nginx and Basic Auth Tools

Ubuntu / Debian：

```bash
sudo apt update
sudo apt install -y nginx apache2-utils
```

### 2. Create Basic Auth User

```bash
sudo htpasswd -c /etc/nginx/.htpasswd monitor_user
```

系統會要求輸入 Dashboard 的登入密碼。

### 3. Configure Nginx Reverse Proxy

建立設定檔：

```bash
sudo nano /etc/nginx/sites-available/server-monitor
```

加入：

```nginx
server {
    listen 80;
    server_name _;

    auth_basic "Server Monitor";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

啟用設定：

```bash
sudo ln -s /etc/nginx/sites-available/server-monitor /etc/nginx/sites-enabled/server-monitor
sudo nginx -t
sudo systemctl restart nginx
```

如果不需要 Nginx 預設網站，可移除：

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl restart nginx
```

完成後即可透過：

```text
http://<SERVER_IP>
```

存取 Dashboard。

> 若服務會經由 Internet 存取，建議再配置 HTTPS/TLS。Basic Auth 本身不會加密 HTTP 傳輸內容。

---

## UFW Firewall（Optional）

如果使用 UFW，可只開放 SSH 與 Nginx 所需連接埠。

> **注意：** 設定防火牆前，請先確認 SSH Port，並保留目前的 SSH 連線。建議另外開一個 Terminal 測試新連線成功後，再關閉原本連線。

例如 SSH 使用 Port `22`：

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw enable
sudo ufw status verbose
```

若 SSH 使用其他 Port，請將 `22` 改成實際的連接埠。

若已設定 HTTPS，通常也需要：

```bash
sudo ufw allow 443/tcp
```

由於 Docker 服務預設只綁定 `127.0.0.1:5000`，通常不需要對外開放 Port `5000`。

---

## Troubleshooting

### Server 顯示 Offline

先從監控主機確認 SSH 是否可正常登入：

```bash
ssh -p <PORT> <USER>@<SERVER_IP>
```

若使用 SSH Key：

```bash
ssh -i ./monitor_key -p <PORT> <USER>@<SERVER_IP>
```

### GPU 資訊沒有顯示

登入被監控主機後確認：

```bash
nvidia-smi
```

如果 `nvidia-smi` 無法正常執行，Server Monitor 也無法取得 GPU 資訊。

### Docker 啟動後看不到頁面

查看服務狀態與 Log：

```bash
docker compose ps
docker compose logs -f
```

並確認本機使用：

```text
http://127.0.0.1:5000
```

### 其他電腦無法直接連線 Port 5000

這是預期行為。預設 Docker Compose 僅將服務綁定至：

```text
127.0.0.1:5000
```

請使用 SSH Tunnel，或設定 Nginx Reverse Proxy。

---

## Security Notes

請勿將下列檔案提交至公開 Git Repository：

```text
servers.json
monitor_key
monitor_key.pub
.env
```

建議 `.gitignore` 至少包含：

```gitignore
.venv/
__pycache__/
*.pyc

servers.json
monitor_key
monitor_key.pub
.env
```

另外建議：

- 正式環境優先使用 SSH Key，不要將伺服器密碼寫入公開檔案。
- 私鑰權限建議設定為 `600`。
- 不建議直接將 Flask / Socket.IO 的 Port `5000` 暴露至 Internet。
- 對外服務建議使用 Nginx，並搭配身份驗證與 HTTPS/TLS。
- 請限制監控帳號權限，只授予讀取系統狀態所需的最低權限。

---

## Notes

Server Monitor 透過 SSH 定期取得遠端主機狀態，因此監控主機必須能連線至各目標 Server 的 SSH Port。

若遠端主機位於不同網段、VPN、防火牆或 Cloud Security Group 後方，也需要確認網路規則允許監控主機連入。

## License

本專案採用 MIT License 授權，詳細內容請參閱 [LICENSE](LICENSE)。
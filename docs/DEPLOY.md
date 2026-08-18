# LINE 客戶服務監控系統 — 部署 SOP (Standard Operating Procedure)

本文件是從零到可用的完成部署步驟，涵蓋：前置需求 → 安裝 Hermes → 一鍵安裝 → 啟動 → 網路設定 → Web UI 設定 → 心跳監控 → 驗收測試 → 疑難排解。

適用對象：任何一台乾淨的 **Linux / Raspberry Pi + Hermes Agent** 裝置。

---

## 0. 架構概覽（部署前先看懂）

```
客戶 ──1:1訊息──> LINE 官方帳號
                      │
                      ▼ Webhook (ngrok/https)
                 Flask 後端 (Port 8080)
                      │
                 ┌────┴────┐
                 │ SQLite  │  messages / contacts / heartbeat 等表
                 └────┬────┘
              crontab 每15分鐘巡檢 (patrol_cron.py)
              crontab 每5分鐘心跳監控 (heartbeat_cron.py)
                      │
              超時無人回覆 →
                ├── Hermes CLI 生成 AI 草稿 (含 RAG 知識庫檢索)
                ├── 通知操作人員 / 管理員
                ├── 嚴重延遲 → 多通道 (Discord/Telegram/Email) 發送
                └── 管理員 Web UI 確認 → LINE 回覆客戶
```

---

## 1. 前置需求

| 項目 | 需求 | 檢查指令 |
|------|------|----------|
| OS | Linux / Raspberry Pi | `uname -a` |
| Python | 3.11+ | `python3 --version` |
| LINE 帳號 | 已開啟 Messaging API | 至 LINE 後台確認 |
| Hermes Agent | 已安裝（AI 草稿用） | `hermes --version` |
| 公網位址 | ngrok / Cloudflare Tunnel | `ngrok --version` |
| sudo 權限 | 建立 systemd 服務需要 | `sudo whoami` |
| git | 拉取代碼 | `git --version` |

> **⚠️ 最重要的一件事**：Hermes Agent 必須先安裝完成，否則 AI 草稿會退化成預設罐頭回覆（系統仍可運作，但沒有 AI 能力）。**先裝 Hermes，再裝本系統。**

---

## 2. 安裝 Hermes Agent（如未安裝）

```bash
# 依 Hermes Agent 官方文件安裝（此處為範例，依版本調整）
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes setup          # 選擇模型提供者並完成設定

# 驗證 AI 呼叫能用（line-monitor 使用此 CLI）
hermes chat -q "你好，請回覆：測試"
```

> line-monitor 的 AI 草稿是透過 `hermes chat -q "<prompt>"` 指令呼叫。只要這條指令能回傳文字，AI 功能就正常。

---

## 3. 一鍵安裝

```bash
git clone https://github.com/MF-Studio-lab/line-monitor.git
cd line-monitor
chmod +x scripts/setup.sh
./scripts/setup.sh
```

`setup.sh` 會自動完成：

1. 建立 Python venv
2. 安裝依賴（Flask / line-bot-sdk / requests）
3. 初始化 SQLite 資料庫（含 messages / contacts / notification_log / settings / **heartbeat** 表）
4. 建立 systemd 服務（line-monitor.service，自動重啟）
5. 設定 crontab（每 15 分鐘巡檢 + 每 5 分鐘心跳監控）

---

## 4. 啟動服務

```bash
sudo systemctl start line-monitor
sudo systemctl status line-monitor      # 確認 active (running)
sudo systemctl enable line-monitor      # 開機自動啟動
```

**驗證 Web UI 已啟動：**

```bash
curl -s localhost:8080/api/health
# 預期回傳 {"status":"ok",...}
```

---

## 5. 設定 LINE Webhook（公網連線）

LINE 需要 HTTPS 公網位址才能送 Webhook 進來。

### 5.1 啟動隧道

```bash
ngrok http 8080
# 或 Cloudflare Tunnel:
# cloudflared tunnel --url http://localhost:8080
```

記錄顯示的 HTTPS 網址，例如 `https://abc123.ngrok.io`。

### 5.2 設定 Webhook URL

本機流程：
1. 瀏覽器開 `http://localhost:8080` → 設定
2. 填入 LINE Channel Access Token → 點「測試連接」
3. 填入 Webhook URL → 儲存

遠端流程（LINE 後台）：
1. 到 [LINE Official Account Manager](https://manager.line.biz)
2. Settings → Messaging API → Webhook
3. 填入 `https://abc123.ngrok.io/webhook` → 啟用 Webhook

> ⚠️ **ngrok 免費版的網址每次重啟會變**。若要永久網址，用 Cloudflare Tunnel 搭配自訂域名，或使用付費 ngrok 靜態網域。

---

## 6. Web UI 初始化設定

開啟 `http://localhost:8080`，依序完成：

### 6.1 LINE 連接
- Channel Access Token（必填）
- Webhook URL（必填）
- 測試連接

### 6.2 通知時間
- 第 1 次提醒（預設 1h，通知操作人員）
- 第 2 次升級（預設 3h，通知管理員）
- 第 3 次升級（預設 6h，嚴重延遲，多通道警報）

### 6.3 通知通道（多樣化，建議至少設 1 個 LINE 以外的）
- **Discord**：填 Webhook URL
- **Telegram**：填 Bot Token + Chat ID
- **Email**：SMTP 主機/帳號/密碼/寄件/收件信箱
- 每個通道都有「測試」按鈕

> 嚴重延遲與心跳異常會透過所有 enable 的通道發送，確保你不看 LINE 也能收到。

### 6.4 知識庫 (RAG)
1. 準備知識文件：過往解決方案、產品規格、FAQ 存成 `.txt` / `.md` / `.rst`
2. 啟用知識庫檢索 → 填資料夾或單檔路徑 → 設 Top-K
3. 用「檢索測試」驗證系統能找到相符文件

### 6.5 心跳監控
- 啟用心跳監控
- 心跳過期上限（預設 60 分鐘，建議 ≥ 巡檢間隔的 4 倍）

### 6.6 成員管理
1. 管理員/操作人員先向官方帳號發一則訊息（讓系統記錄 userId）
2. 在訊息日誌找到 userId
3. 設定 → 成員管理 → 加入並指定角色

---

## 7. 驗收測試（部署完成後必做）

跑完以下檢查，全部通過才算部署完成。

```bash
# 1. 服務狀態
sudo systemctl status line-monitor | head -5

# 2. API 健康檢查
curl -s localhost:8080/api/health          # {status:"ok"}
curl -s localhost:8080/api/stats           # 統計資料
curl -s localhost:8080/api/heartbeat/status

# 3. 心跳記錄（手動觸發一次巡檢，確認 heartbeat 表有資料）
sudo -u $USER curl -s -X POST localhost:8080/api/heartbeat/record
```

**Web UI 驗證：**

| 頁面 | 檢查項目 | 預期結果 |
|------|----------|----------|
| 儀表板 `/` | 統計卡片 + MTTR + 心跳狀態 | 全部正常顯示 |
| 訊息日誌 `/messages` | 載入無錯誤 | 200 + 分頁可用 |
| SLA 報表 `/reports` | MTTR 圖表載入 | 200 + 圖表顯示 |
| 設定 `/settings` | LINE 測試、通道測試、RAG 測試 | 各測試正常 |

**端到端實測：**
1. 用一支測試手機向官方帳號發送訊息
2. 確認後台能收到（`curl -s localhost:8080/api/messages`）
3. （需等待 1 小時）確認超時提醒能送達操作人員
4. 在 Web UI 確認/發送 AI 草稿

---

## 8. 心跳/健康自查（長期維護）

系统已內建兩道防線：

| 機制 | 頻率 | 作用 |
|------|------|------|
| 巡檢 `patrol_cron.py` | 每 15 分鐘 | 檢查超時訊息並通知 |
| 心跳 `heartbeat_cron.py` | 每 5 分鐘 | 檢查巡檢是否逾期未跑，異常即警報 |

如果「巡檢」連續超過設定值（預設 60 分鐘）未執行，`heartbeat_cron.py` 會自動發送警報到所有啟用通道，避免伺服器當機/只剩系統失效卻無人發現。

查看日誌：
```bash
tail -20 data/patrol.log       # 巡檢紀錄
tail -20 data/heartbeat.log    # 心跳紀錄
```

---

## 9. 疑難排解

| 症狀 | 可能原因 | 解法 |
|------|----------|------|
| `/api/health` 沒回應 | 服務沒啟動 | `sudo systemctl start line-monitor`，看 `sudo journalctl -u line-monitor -n 50` |
| Webhook 收到但無反應 | Webhook URL 沒設定到 LINE 後台 | 確認 5.2 步驟，LINK 後台測試 Webhook |
| Webhook 403 | Channel Secret 填錯 | 設定頁確認 channel_secret |
| AI 草稿是罐頭回覆 | Hermes 未裝 / `hermes chat -q` 失敗 | `hermes chat -q "hi"` 測試，確認 CLI 能用 |
| 收不到 Discord/Telegram/Email | 通道未啟用或設定錯 | 用各通道「測試」按鈕排查 |
| 心跳一直異常 | crontab 沒設心跳監控 | 確認 `crontab -l` 有 `heartbeat_cron.py` |
| 心跳誤報 | 上限設太低 | 心跳上限設 ≥ 巡檢間隔的 4 倍 |

---

## 10. 多台裝置部署注意事項

本系統是通用方案，可在多台部署。**但同一時間只應有一台「主動監控」某個 LINE 官方帳號。**

- ⚠️ **LINE token 綁定官方帳號**：同一 token 若被兩台同時使用，兩台都會收到 Webhook 並重複發送提醒。
- 如果是**備援/災難復原**：備援機建議啟動後**停用 LINE push**，僅保留心跳/健康監控，等主機失效再接手。
- 每台裝置的 `data/config.json`、`.env`、LINE token、通道設定**都是獨立的**，不會也不應進版控（已 gitignore）。

---

## 附錄 A：手動啟動（非 systemd，測試用）

```bash
cd line-monitor
source venv/bin/activate
FLASK_DEBUG=0 python app.py
# 或指定 Port
PORT=9090 python app.py
```

## 附錄 B：依賴清單

```
flask>=3.0
line-bot-sdk>=3.14
requests>=2.31
```

> 多通道通知 (Discord/Telegram/Email)、心跳監控、RAG 檢索、SLA 報表都是**純 Python 標準+已依賴**，不需額外套件。
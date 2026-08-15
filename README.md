# LINE 客戶服務監控系統

監測 LINE Official Account 客戶訊息，當客戶提問後 1~2 小時內無人回覆時，自動彙整問題通知管理員，並生成 AI 回覆草稿供管理員確認後發送。

## 功能特色

- **自動監測**：透過 LINE Messaging API Webhook 接收所有客戶 1:1 訊息
- **超時通知**：可設定第1/2/3次提醒時間（預設 1h / 3h / 6h）
- **通知抑制**：同一訊息不重複通知，避免 Notification Fatigue
- **批次彙整**：多條超時訊息合併成 1 則通知，不逐條轟炸
- **AI 草稿回覆**：整合 Hermes Agent AI 生成回覆建議
- **管理員確認**：管理員透過 Web UI 確認/編輯後才發送給客戶
- **角色管理**：區分管理員 / 操作人員 / 客戶，各角色收到不同層級通知
- **Web UI 儀表板**：即時查看待回覆數、嚴重延遲、今日統計、訊息趨勢圖

## 系統架構

```
客戶 ──1:1訊息──> LINE Official Account
                        │
                        ▼ Webhook
                   Flask 後端 (Port 8080)
                        │
                   ┌────┴────┐
                   │ SQLite  │  記錄所有訊息
                   └────┬────┘
                        │
              crontab 每 15 分鐘巡檢
                        │
              超時無人回覆 →
                ├── AI 彙整問題 + 生成草稿
                ├── LINE push → 通知操作人員
                ├── LINE push → 通知管理員 (含草稿)
                └── 管理員 Web UI 確認 → 發送回覆
```

## 訊息狀態生命週期

```
pending (待回覆)
  │ 1h 無人回覆
  ▼
reminded_1 (已提醒操作人員)
  │ 3h 無人回覆
  ▼
reminded_2 (已升級通知管理員)
  │ 6h 無人回覆
  ▼
escalated (嚴重延遲)
  │ 操作人員回覆
  ▼
resolved (已解決)
```

## 快速部署

### 前置需求

- Linux / Raspberry Pi (Python 3.11+)
- LINE Official Account 已開啟 Messaging API
- Hermes Agent 已安裝（AI 草稿功能）
- ngrok 或 Cloudflare Tunnel（公網 Webhook 位址）

### 一鍵安裝

```bash
git clone https://github.com/MF-Studio-lab/line-monitor.git
cd line-monitor
chmod +x scripts/setup.sh
./scripts/setup.sh
```

安裝腳本會完成：
1. 建立 Python venv
2. 安裝 Flask + LINE Bot SDK
3. 初始化 SQLite 資料庫
4. 建立 systemd 服務 (line-monitor.service)
5. 設定 crontab 每 15 分鐘巡檢

### 啟動服務

```bash
sudo systemctl start line-monitor
sudo systemctl status line-monitor
```

### 設定 LINE Webhook

1. 打開瀏覽器 → `http://localhost:8080` → 進入「設定」頁
2. 填入 LINE Channel Access Token
3. 啟動 ngrok tunnel：
   ```bash
   ngrok http 8080
   ```
4. 將 ngrok 產生的 HTTPS URL 填入設定頁的 Webhook URL
5. 到 LINE Official Account Manager → Settings → Messaging API → 填入 Webhook URL：`https://xxx.ngrok.io/webhook`

### 新增成員

1. 請管理員/操作人員先向官方帳號發送一則訊息（讓系統記錄 userId）
2. 到 Web UI → 設定 → 成員管理 → 輸入姓名 + userId → 選擇角色 → 加入

### 設定 crontab 巡檢（手動方式）

```bash
crontab -e
# 加入以下行：
*/15 * * * * cd /home/mf-claw/line-monitor && venv/bin/python scripts/patrol_cron.py >> data/patrol.log 2>&1
```

## Web UI 頁面

- **儀表板**：即時統計卡片、待回覆清單with計時器、今日統計、7日訊息趨勢圖
- **訊息日誌**：日期/狀態/關鍵字篩選，AI 草稿預覽 + 確認發送/編輯/標記已處理
- **設定**：LINE 連接、通知時間、通知抑制/批次彙整開關、成員管理、AI 模型/公司資訊

## 技術棧

| 項目 | 技術 |
|------|------|
| 後端 | Flask 3.x |
| 資料庫 | SQLite |
| LINE SDK | line-bot-sdk |
| 前端 | Jinja2 + Tailwind CSS CDN |
| 圖表 | Chart.js CDN |
| AI | Hermes Agent CLI |
| 排程 | crontab |
| 服務 | systemd |

## 與其他 Hermes Agent 共用部署

本專案設計為通用方案，其他 Hermes Agent 環境只需：

```bash
git clone https://github.com/MF-Studio-lab/line-monitor.git
cd line-monitor
./scripts/setup.sh
```

然後各自在 Web UI 設定頁填入自己的 LINE token 即可。

## 設定值預設

| 參數 | 預設 |
|------|------|
| 第1次提醒 | 1 小時（通知操作人員） |
| 第2次升級 | 3 小時（通知管理員） |
| 第3次升級 | 6 小時（嚴重延遲） |
| 巡檢間隔 | 15 分鐘 |
| 通知抑制 | 開啟 |
| 批次彙整 | 開啟 |
| 自動發送 | 關閉（管理員確認後才發送） |

## License

MIT License - Copyright (c) 2026 GREEN INDUSTRY CO., LTD.

#!/bin/bash
# LINE 客戶服務監控系統 - 部署腳本
# 適用: Raspberry Pi / Linux (Python 3.11+)

set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "========================================"
echo "  LINE 客戶服務監控系統 - 部署安裝"
echo "========================================"
echo ""

# 1. 建立 venv
echo "[1/5] 建立 Python 虛擬環境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
echo "  ✅ venv 已就緒"

# 2. 安裝依賴
echo "[2/5] 安裝 Python 依賴..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  ✅ 依賴安裝完成"

# 3. 初始化資料庫
echo "[3/5] 初始化 SQLite 資料庫..."
python3 -c "from database import init_db; init_db()"
echo "  ✅ 資料庫已初始化"

# 4. 建立 systemd 服務
echo "[4/5] 建立 systemd 服務..."
SERVICE_FILE="/etc/systemd/system/line-monitor.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=LINE Customer Service Monitor
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python app.py
Restart=on-failure
RestartSec=5
Environment=PYTHONPATH=$PROJECT_DIR

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable line-monitor
echo "  ✅ systemd 服務已建立 (line-monitor.service)"

# 5. 設定 crontab 巡檢
echo "[5/5] 設定 crontab 巡檢..."
CRON_LINE="*/15 * * * * cd $PROJECT_DIR && venv/bin/python scripts/patrol_cron.py >> data/patrol.log 2>&1"
( crontab -l 2>/dev/null | grep -v "patrol_cron.py" ; echo "$CRON_LINE" ) | crontab -
echo "  ✅ crontab 已設定 (每15分鐘巡檢)"

echo ""
echo "========================================"
echo "  🎉 部署完成！"
echo "========================================"
echo ""
echo "啟動服務:"
echo "  sudo systemctl start line-monitor"
echo "  sudo systemctl status line-monitor"
echo ""
echo "Web UI: http://localhost:8080"
echo ""
echo "下一步:"
echo "  1. 打開瀏覽器 http://localhost:8080"
echo "  2. 進入「設定」頁面填入 LINE Channel Access Token"
echo "  3. 設定 ngrok tunnel 取得公網位址"
echo "  4. 在 LINE Official Account Manager 設定 Webhook URL"
echo "  5. 新增管理員和操作人員的 LINE userId"
echo ""
echo "ngrok tunnel:"
echo "  ngrok http 8080"
echo "  → 取得 https URL → 填入設定頁的 Webhook URL"
echo "  → 在 LINE 後台設定 Webhook URL: https://xxx.ngrok.io/webhook"

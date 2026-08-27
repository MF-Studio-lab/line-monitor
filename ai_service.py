"""
ai_service.py - AI 草稿生成服務
優先呼叫本地 Ollama (qwen2.5:7b-instruct)，失敗再 fallback Hermes CLI
"""

import os
import subprocess
import json
import rag
from config import load_config

# ============================================================
# 本地 Ollama 設定 (OpenAI 相容 API)
# ============================================================
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_TIMEOUT = 60  # 秒

try:
    import openai
    _ollama_client = openai.OpenAI(base_url=OLLAMA_BASE, api_key="ollama")
except ImportError:
    _ollama_client = None

# ============================================================
# Hermes CLI 設定
# ============================================================
HERMES_CMD = "hermes"
HERMES_TIMEOUT = 60  # 秒


def _run_hermes(prompt):
    """
    呼叫 hermes chat -q "prompt" 並回傳結果字串
    失敗時回傳空字串（由呼叫端自行決定 fallback）
    """
    try:
        result = subprocess.run(
            [HERMES_CMD, "chat", "-q", prompt],
            capture_output=True,
            text=True,
            timeout=HERMES_TIMEOUT,
        )
        return result.stdout.strip() if result.stdout else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return ""


def _run_ollama(prompt):
    """
    呼叫本地 Ollama (OpenAI 相容 API)
    失敗時回傳空字串
    """
    if _ollama_client is None:
        return ""
    try:
        resp = _ollama_client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.3,
            timeout=OLLAMA_TIMEOUT,
        )
        return resp.choices[0].message.content.strip() if resp.choices else ""
    except Exception:
        return ""


# ============================================================
# 意圖分類：判斷訊息是否為「詢問/需求」（需回覆）vs 一般資訊/問候
# ============================================================

# 詢問意圖關鍵字（中英混合）
INQUIRY_KEYWORDS = [
    # 中文疑問詞
    "怎麼", "如何", "怎樣", "為什麼", "為何", "哪裡", "哪裡有", "哪位",
    "什麼", "甚麼", "誰", "何時", "多久", "多少", "多少錢", "多少錢",
    "能不能", "可不可以", "可以嗎", "可以麻煩", "請問", "想問", "想請教",
    "有沒有", "有無", "是否", "會不會", "需不需要", "要不要",
    "問題", "故障", "錯誤", "異常", "壞了", "修", "維修", "更換", "換",
    "設定", "調整", "參數", "校正", "校準", "安裝", "接線", "接法",
    "報價", "價格", "費用", "收費", "方案", "建議", "推薦", "選型",
    "規格", "尺寸", "重量", "功率", "電壓", "電流", "壓力", "流量",
    # 英文疑問詞
    "how", "what", "why", "where", "when", "who", "which", "whose",
    "can you", "could you", "would you", "please", "help", "question",
    "problem", "issue", "error", "fault", "fail", "repair", "fix",
    "replace", "change", "setting", "config", "parameter", "calibrat",
    "install", "wire", "wiring", "quote", "price", "cost", "spec",
    # 標點
    "？", "?",
]

# 非詢問意圖關鍵字（單純提供資訊、問候、感謝、確認）
# 注意：避免使用可能作為詢問開頭的詞（如「你好」、「您好」）
NON_INQUIRY_KEYWORDS = [
    "謝謝", "感謝", "thanks", "thank you",
    "早安", "午安", "晚安", "hi", "hello",
    "收到", "確認", "ok", "OK", "Ok", "好", "沒問題", "沒事",
    "沒問題", "無問題", "不客氣",
    "電話", "手機", "聯絡", "line id", "lineid", "wechat", "微信",
    "名片", "聯絡人", "負責人", "經理", "主管",
    "附件", "照片", "圖片", "檔案", "pdf", "報價單", "單據",
    "已寄出", "已發送", "已發出", "已郵寄", "已快遞",
    "辛苦了", "辛苦", "麻煩了", "打擾了",
]

def classify_intent(text: str) -> str:
    """
    判斷訊息意圖
    回傳: "inquiry" (需回覆/詢問) 或 "info" (一般資訊/問候/感謝)
    """
    if not text:
        return "info"
    
    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    
    # 1. 完全匹配非詢問關鍵字（訊息內容完全等於該關鍵字）
    # 例如：單獨發送 "謝謝"、"收到"、"早安" 等
    for kw in NON_INQUIRY_KEYWORDS:
        if text_lower == kw.lower():
            return "info"
    
    # 2. 極短訊息且包含非詢問關鍵字（長度 <= 8 字元）
    # 但若同時包含詢問關鍵字，仍視為詢問
    if len(text_stripped) <= 8:
        has_non_inquiry = any(kw.lower() in text_lower for kw in NON_INQUIRY_KEYWORDS)
        has_inquiry = any(iq.lower() in text_lower for iq in INQUIRY_KEYWORDS)
        if has_non_inquiry and not has_inquiry:
            return "info"
    
    # 3. 檢查詢問關鍵字
    for kw in INQUIRY_KEYWORDS:
        if kw.lower() in text_lower:
            return "inquiry"
    
    # 4. 句子結構判斷：包含問號
    if "？" in text or "?" in text:
        return "inquiry"
    
    # 5. 長度較長且無明確關鍵字，預設為資訊類
    return "info"


def _fallback_draft(prompt):
    """Hermes 不可用時的預設回覆草稿"""
    return """您好，感謝您的來訊。我們已收到您的訊息，將儘快由專人為您回覆。
如有急迫需求，歡迎致電本公司客服專線，謝謝您的耐心等候。"""


def generate_draft(customer_name, message_text, context=""):
    """
    生成回覆草稿

    customer_name: 客戶名稱
    message_text: 客戶訊息內容
    context: 額外上下文 (可選，例如先前對話紀錄)
    回傳: AI 生成的草稿字串
    """
    config = load_config()
    company = config.get("company", {}).get("name", "GREEN INDUSTRY CO., LTD.")
    company_info = config.get("ai", {}).get("company_info", "")
    rag_cfg = config.get("rag", {})

    # RAG 知識庫檢索
    kb_block = ""
    if rag_cfg.get("enabled") and rag_cfg.get("kb_path"):
        top_k = int(rag_cfg.get("top_k", 3))
        snippet_max_len = int(rag_cfg.get("snippet_max_len", 400))
        results = rag.retrieve(message_text, rag_cfg.get("kb_path", ""), top_k, snippet_max_len=snippet_max_len)
        ctx = rag.format_context(results)
        if ctx:
            kb_block = "知識庫參考資料（請據此回答具體問題，不要編造）：\n" + ctx

    prompt = f"""你是 {company} 的 LINE 客服專員，需要回覆客戶的 1:1 訊息。
請用繁體中文撰寫一則禮貌、專業、簡潔的回覆訊息。
公司資訊: {company_info}
{kb_block}
客戶名稱: {customer_name}
客戶訊息: {message_text}
{"上下文: " + context if context else ""}

請只輸出回覆內容，不要加多餘說明。回覆應該:
1. 確認收到客戶的訊息
2. 正面回應客戶的問題或需求
3. 若有知識庫資料，優先依據知識庫內容回答規格/價格/技術類問題
4. 保持親切專業的語氣"""

    # 優先順序：Ollama (本地) -> Hermes -> 靜態 fallback
    draft = _run_ollama(prompt)
    if not draft:
        draft = _run_hermes(prompt)
    if not draft:
        draft = _fallback_draft(prompt)
    return draft


def summarize_messages(msg_list):
    """
    批次彙整多條待回覆訊息成摘要
    msg_list: 含 message_text, user_name, message_time 等欄位的 dict 清單
    回傳: 摘要字串
    """
    if not msg_list:
        return "目前沒有待回覆訊息。"

    # 組合訊息描述
    lines = []
    for i, msg in enumerate(msg_list, 1):
        name = msg.get("user_name") or msg.get("user_id", "未知")
        text = msg.get("message_text", "")[:200]
        time = msg.get("message_time", "未知")
        lines.append(f"訊息{i} - [{name}] ({time}): {text}")

    combined = "\n".join(lines)
    count = len(msg_list)

    prompt = f"""你是客服系統的彙整助手。以下有 {count} 條待回覆的 LINE 客戶訊息。
請彙整成簡潔的摘要，方便客服人員快速掌握狀況。每條訊息列一行，說明客戶問題重點。

待回覆訊息:
{combined}

请以以下格式彙整:
• [客戶名] 問題摘要 (訊息時間)
每行一條，語氣簡潔。"""

    # 優先順序：Ollama (本地) -> Hermes -> 本地彙整
    summary = _run_ollama(prompt)
    if not summary:
        summary = _run_hermes(prompt)
    if not summary:
        # Fallback: 本地彙整（不呼叫 _fallback_draft）
        summary = f"共 {count} 條待回覆訊息:\n" + "\n".join(
            f"• [{m.get('user_name') or '客戶'}] {m.get('message_text', '')[:80]}..."
            for m in msg_list
        )
    return summary

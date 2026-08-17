"""
ai_service.py - AI 草稿生成服務
透過 Hermes CLI (hermes chat -q) 呼叫 AI 生成回覆草稿與批次彙整
"""

import subprocess
import json
import rag
from config import load_config

HERMES_CMD = "hermes"
TIMEOUT = 60  # 秒


def _run_hermes(prompt):
    """
    呼叫 hermes chat -q "prompt" 並回傳結果字串
    失敗時回傳空字串
    """
    try:
        result = subprocess.run(
            [HERMES_CMD, "chat", "-q", prompt],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        return result.stdout.strip() if result.stdout else ""
    except FileNotFoundError:
        # hermes 指令不存在，使用 fallback
        return _fallback_draft(prompt)
    except subprocess.TimeoutExpired:
        return _fallback_draft(prompt)
    except Exception:
        return _fallback_draft(prompt)


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
        results = rag.retrieve(message_text, rag_cfg.get("kb_path", ""), top_k)
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
4. 保持親切專業的語氣
"""

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
每行一條，語氣簡潔。
"""

    summary = _run_hermes(prompt)
    if not summary:
        # Fallback: 手動彙整
        summary = f"共 {count} 條待回覆訊息:\n" + "\n".join(
            f"• [{m.get('user_name') or '客戶'}] {m.get('message_text', '')[:80]}..."
            for m in msg_list
        )
    return summary

"""
rag.py - 知識庫檢索 (RAG) 兩階段檢索版
階段 1：讀取輕量索引 (index.jsonl)，用關鍵字快速篩選 Top-K
階段 2：讀取完整 Markdown 檔案，做詳細評分並回傳片段
"""

import json
import os
import re
from pathlib import Path

INDEX_FILE = Path("/mnt/green/GREEN_File/QA/index.jsonl")
QA_ROOT = Path("/mnt/green/GREEN_File/QA")

# 簡單記憶體快取
_INDEX_CACHE = None
_FULL_TEXT_CACHE = {}


def _load_index():
    """載入輕量索引（只載入一次）"""
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE

    if not INDEX_FILE.exists():
        return []

    records = []
    with INDEX_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    _INDEX_CACHE = records
    return records


def _read_full_text(source_file: str) -> str:
    """讀取完整 Markdown 內容（帶快取）"""
    if source_file in _FULL_TEXT_CACHE:
        return _FULL_TEXT_CACHE[source_file]

    full_path = QA_ROOT / source_file
    try:
        text = full_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    _FULL_TEXT_CACHE[source_file] = text
    return text


def _tokenize(text: str) -> dict:
    """中英混雜分詞"""
    tokens = {"ascii": set(), "cjk": set(), "bigram": set()}
    # 英文/數字詞
    tokens["ascii"] |= set(re.findall(r"[a-zA-Z0-9]{2,}", text.lower()))
    # 中文字
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    tokens["cjk"] |= set(cjk_chars)
    tokens["bigram"] |= set("".join(cjk_chars[i:i+2]) for i in range(len(cjk_chars)-1))
    return tokens


def _score(text: str, query_tokens: dict) -> int:
    """關鍵字加權評分"""
    if not any(query_tokens.values()):
        return 0
    body = text.lower()
    score = 0
    for w in query_tokens["ascii"]:
        score += body.count(w) * 3
    for w in query_tokens["bigram"]:
        score += body.count(w) * 2
    for w in query_tokens["cjk"]:
        score += body.count(w) * 1
    return score


def _extract_snippet(text: str, query_tokens: dict, max_len: int = 800) -> str:
    """從文本中提取最相關的片段"""
    if len(text) <= max_len:
        return text

    # 找出包含最多查詢詞的窗口
    query_words = set()
    query_words.update(query_tokens["ascii"])
    query_words.update(query_tokens["bigram"])
    query_words.update(query_tokens["cjk"])

    best_start = 0
    best_count = -1
    step = max_len // 4

    for start in range(0, len(text) - max_len + 1, step):
        window = text[start:start + max_len].lower()
        count = sum(window.count(w) for w in query_words)
        if count > best_count:
            best_count = count
            best_start = start

    return text[best_start:best_start + max_len]


def retrieve(query: str, kb_path: str = "", top_k: int = 3, stage1_k: int = 10, snippet_max_len: int = 400):
    """
    兩階段檢索
    回傳 [(source_name, score, snippet), ...]
    """
    # 階段 1：載入索引，關鍵字快速篩選
    index_records = _load_index()
    if not index_records:
        return []

    query_tokens = _tokenize(query)

    # 計算每個案例的關鍵字匹配分
    stage1_scores = []
    for rec in index_records:
        # 將關鍵字列表合併為文本進行評分
        keyword_text = " ".join(rec.get("keywords", []))
        score = _score(keyword_text, query_tokens)
        if score > 0:
            stage1_scores.append((rec, score))

    # 取分數最高的前 stage1_k 筆
    stage1_scores.sort(key=lambda x: x[1], reverse=True)
    candidates = [rec for rec, _ in stage1_scores[:stage1_k]]

    if not candidates:
        return []

    # 階段 2：讀取完整檔案，詳細評分
    stage2_results = []
    for rec in candidates:
        full_text = _read_full_text(rec["source_file"])
        if not full_text:
            continue

        score = _score(full_text, query_tokens)
        if score > 0:
            snippet = _extract_snippet(full_text, query_tokens, max_len=snippet_max_len)
            # source_name 使用 case_id
            source_name = rec["case_id"]
            stage2_results.append((source_name, score, snippet))

    # 最終排序
    stage2_results.sort(key=lambda x: x[1], reverse=True)
    return stage2_results[:top_k]


def format_context(results):
    """將檢索結果格式化為可放入 prompt 的上下文文字"""
    if not results:
        return ""
    lines = ["【知識庫參考資料】"]
    for i, (name, score, snippet) in enumerate(results, 1):
        lines.append(f"[{i}] 案例: {name} (相關度: {score})")
        lines.append(snippet.strip())
        lines.append("")
    return "\n".join(lines)


def clear_cache():
    """清除快取（重建索引後呼叫）"""
    global _INDEX_CACHE, _FULL_TEXT_CACHE
    _INDEX_CACHE = None
    _FULL_TEXT_CACHE.clear()
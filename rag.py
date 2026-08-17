"""
rag.py - 知識庫檢索 (RAG)
從設定的知識庫路徑 (kb_path) 讀取 .txt/.md 文件，
依客戶問題內容做關鍵字相似度檢索，回傳最相關的知識片段，
供 ai_service 產生更精準的專業回覆。
"""

import os
from pathlib import Path

_PATHS = {}


def _load_kb(kb_path):
    """載入知識庫文件清單，回傳 [(filename, text)]"""
    if kb_path in _PATHS:
        return _PATHS[kb_path]
    segments = []
    p = Path(kb_path)
    if p.is_file():
        segments = [(_base_name(str(p)), _read_file(p))]
    elif p.is_dir():
        for f in sorted(p.iterdir()):
            if f.suffix.lower() in (".txt", ".md", ".rst"):
                segments.append((_base_name(str(f)), _read_file(f)))
    _PATHS[kb_path] = segments
    return segments


def _base_name(path):
    return Path(path).name


def _read_file(p):
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except IOError:
        return ""


def _totally_clear_cache():
    _PATHS.clear()


def retrieve(query, kb_path, top_k=3):
    """
    檢索與 query 最相關的知識片段。
    回傳 [(filename, score, snippet), ...]
    """
    if not kb_path or not os.path.exists(kb_path):
        return []
    segments = _load_kb(kb_path)
    if not segments:
        return []

    query_words = _tokenize(query)
    scored = []
    for name, text in segments:
        score = _score(text, query_words)
        if score > 0:
            snippet = text[:800]
            scored.append((name, score, snippet))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _tokenize(text):
    """中英混雜：英文/數字按詞斷、中文切 1-2 字元，回傳 token 集合（含權重類型）"""
    import re
    tokens = {"ascii": set(), "cjk": set(), "bigram": set()}
    # 英文與數字詞
    tokens["ascii"] |= set(re.findall(r"[a-zA-Z0-9]{2,}", text.lower()))
    # 中文字 (單字 + 相鄰雙字組)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    tokens["cjk"] |= set(cjk_chars)
    tokens["bigram"] |= set(
        "".join(cjk_chars[i:i + 2]) for i in range(len(cjk_chars) - 1)
    )
    return tokens


def _score(text, query_tokens):
    """以 token 出現次數加權計分。
    ASCII 詞組權重高、中文雙字組中等、單字低，避免單字暴衝導致誤判。
    """
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


def format_context(results):
    """將檢索結果格式化為可放入 prompt 的上下文文字"""
    if not results:
        return ""
    lines = ["【知識庫參考資料】"]
    for i, (name, score, snippet) in enumerate(results, 1):
        lines.append(f"[{i}] 來源: {name}")
        lines.append(snippet.strip())
        lines.append("")
    return "\n".join(lines)
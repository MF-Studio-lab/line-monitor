#!/usr/bin/env python3
"""
build_kb_index.py - 建立 QA 知識庫索引（輕量版）
只索引：case_id、source_file、目錄名稱關鍵字
不解析內文，不分塊，極速建立

用法:
    python scripts/build_kb_index.py
"""

import json
from pathlib import Path
from datetime import datetime

# === 設定 ===
QA_ROOT = Path("/mnt/green/GREEN_File/QA")
INDEX_OUTPUT = QA_ROOT / "index.jsonl"
MARKDOWN_DIR_NAME = "00_文字"


def extract_keywords_from_dirname(dirname: str) -> list[str]:
    """從目錄名稱提取關鍵字（以底線分割）"""
    # 移除日期前綴 2026-07-23_
    name = dirname
    if name[:10].count('-') == 2 and name[10] == '_':
        name = name[11:]
    # 以底線分割並過濾空字串
    return [w for w in name.split('_') if w]


def main():
    print(f"[INFO] 掃描目錄: {QA_ROOT}")
    print(f"[INFO] 目標子目錄: {MARKDOWN_DIR_NAME}")
    print(f"[INFO] 輸出索引: {INDEX_OUTPUT}")

    md_files = list(QA_ROOT.rglob(f"{MARKDOWN_DIR_NAME}/*.md"))
    print(f"[INFO] 找到 {len(md_files)} 個 Markdown 檔案")

    if not md_files:
        print("[WARN] 沒有找到任何檔案，結束")
        return

    records = []
    for md_path in md_files:
        # 取得案例目錄名（父目錄的父目錄）
        case_dir = md_path.parent.parent
        case_id = case_dir.name

        # 從目錄名提取關鍵字
        keywords = extract_keywords_from_dirname(case_id)

        # 相對路徑
        rel_path = str(md_path.relative_to(QA_ROOT))

        record = {
            "case_id": case_id,
            "source_file": rel_path,
            "keywords": keywords,
            "indexed_at": datetime.now().isoformat(),
        }
        records.append(record)
        print(f"  ✅ {case_id}  (關鍵字: {', '.join(keywords[:5])}...)")

    # 寫入 JSONL
    with INDEX_OUTPUT.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n[DONE] 索引已寫入: {INDEX_OUTPUT} ({len(records)} 筆)")


if __name__ == "__main__":
    main()
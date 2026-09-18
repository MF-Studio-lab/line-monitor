"""
print_handler.py - LINE 圖片/檔案列印處理模組
支援：從 LINE 下載圖片/PDF/文件 → 轉 PDF → 送 CUPS 列印
需安裝：pillow, pypdf, requests (已有)
系統需：cups-client, printer-driver-escpr (Epson), brlaser (Brother)
"""

import os
import tempfile
import subprocess
import shutil
import requests
from pathlib import Path
from config import load_config
import database as db

# 列印相關設定
PRINT_CONFIG_DEFAULTS = {
    "enabled": True,
    "default_printer": "Epson_L365_239_escpr",  # 預設印表機
    "allowed_roles": ["admin", "operator"],      # 允許列印的角色
    "allowed_types": ["image", "file"],          # 允許的訊息類型
    "max_file_size_mb": 20,                      # 最大檔案大小 (MB)
    "allowed_extensions": [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".txt", ".md"],
    "fit_to_page": True,
    "media": "A4",
    "scaling": 90,
}

# 支援的印表機對應（名稱 -> CUPS 隊列名）
PRINTER_MAP = {
    "epson": "Epson_L365_239_escpr",
    "l365": "Epson_L365_239_escpr",
    "brother": "Brother_HL-L2320D_212",
    "hl-l2320d": "Brother_HL-L2320D_212",
    "fuji": "FX_DocuPrint_M225_dw",
    "docuprint": "FX_DocuPrint_M225_dw",
    "m225": "FX_DocuPrint_M225_dw",
}


def get_print_config():
    """取得列印設定（合併預設值）"""
    config = load_config()
    print_cfg = config.get("print", {})
    result = PRINT_CONFIG_DEFAULTS.copy()
    result.update(print_cfg)
    return result


def is_user_authorized(user_id):
    """檢查用戶是否有列印權限（admin/operator）"""
    contact = db.get_contact(user_id)
    if not contact:
        return False
    allowed = get_print_config().get("allowed_roles", ["admin", "operator"])
    return contact.get("role") in allowed


def get_cups_printers():
    """取得系統可用的 CUPS 印表機清單"""
    try:
        result = subprocess.run(
            ["lpstat", "-p"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        printers = []
        for line in result.stdout.strip().split("\n"):
            if line.startswith("printer "):
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[1]
                    status = " ".join(parts[2:]) if len(parts) > 2 else "unknown"
                    printers.append({"name": name, "status": status})
        return printers
    except Exception as e:
        return [{"error": str(e)}]


def resolve_printer_name(printer_hint):
    """將使用者指定的印表機提示轉為實際 CUPS 隊列名"""
    if not printer_hint:
        return get_print_config().get("default_printer", "Epson_L365_239_escpr")

    hint = printer_hint.lower().strip()
    # 直接匹配 CUPS 隊列名
    printers = get_cups_printers()
    for p in printers:
        if hint == p["name"].lower():
            return p["name"]
    # 模糊匹配
    for key, cups_name in PRINTER_MAP.items():
        if key in hint:
            return cups_name
    # 回傳預設
    return get_print_config().get("default_printer", "Epson_L365_239_escpr")


def download_line_content(message_id, message_type):
    """
    從 LINE 下載圖片/檔案內容
    回傳 (success, local_path_or_error, content_type)
    """
    config = load_config()
    token = config.get("line", {}).get("channel_access_token", "")
    if not token:
        return False, "LINE token 未設定", None

    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(url, headers=headers, timeout=60, stream=True)
        if resp.status_code != 200:
            return False, f"下載失敗: {resp.status_code} {resp.text}", None

        # 判斷副檔名
        content_type = resp.headers.get("Content-Type", "")
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/bmp": ".bmp",
            "image/tiff": ".tiff",
            "application/pdf": ".pdf",
            "text/plain": ".txt",
        }
        ext = ext_map.get(content_type, ".bin")

        # 檔案大小檢查
        max_size = get_print_config().get("max_file_size_mb", 20) * 1024 * 1024
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > max_size:
            return False, f"檔案過大 ({content_length} bytes > {max_size} bytes)", None

        # 寫入暫存檔
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > max_size:
                    os.unlink(f.name)
                    return False, "下載中檔案超過大小限制", None
                f.write(chunk)
            temp_path = f.name

        return True, temp_path, content_type

    except requests.Timeout:
        return False, "下載逾時", None
    except Exception as e:
        return False, f"下載錯誤: {e}", None


def convert_to_pdf(input_path, content_type):
    """
    將各種格式轉為 PDF（供 CUPS 列印）
    回傳 (success, pdf_path_or_error)
    """
    ext = Path(input_path).suffix.lower()
    cfg = get_print_config()

    # 已是 PDF
    if ext == ".pdf":
        return True, input_path

    # 圖片轉 PDF
    if ext in [".jpg", ".jpeg", ".png", ".bmp", ".tiff"]:
        try:
            from PIL import Image
            img = Image.open(input_path)
            # 轉 RGB（去除 alpha 通道）
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            pdf_path = input_path.rsplit(".", 1)[0] + ".pdf"
            img.save(pdf_path, "PDF", resolution=200)
            return True, pdf_path
        except ImportError:
            return False, "缺少 Pillow 套件 (pip install pillow)"
        except Exception as e:
            return False, f"圖片轉 PDF 失敗: {e}"

    # 文字/Markdown/DOCX 轉 PDF - 使用 pandoc + xelatex 支援中文
    if ext in [".txt", ".md", ".docx"]:
        try:
            pdf_path = input_path.rsplit(".", 1)[0] + ".pdf"
            # 使用 pandoc + xelatex，指定中文字體
            result = subprocess.run(
                ["pandoc", input_path, "-o", pdf_path, "--pdf-engine=xelatex",
                 "-V", "geometry:margin=2cm", "-V", "fontsize=10pt",
                 "-V", "mainfont=Noto Serif CJK TC",
                 "-V", "monofont=Noto Sans Mono CJK TC"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0 and os.path.exists(pdf_path):
                return True, pdf_path
            # fallback: 嘗試不指定字體
            result = subprocess.run(
                ["pandoc", input_path, "-o", pdf_path, "--pdf-engine=xelatex",
                 "-V", "geometry:margin=2cm", "-V", "fontsize=10pt"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0 and os.path.exists(pdf_path):
                return True, pdf_path
            return False, f"pandoc 轉換失敗: {result.stderr}"
        except FileNotFoundError:
            return False, "缺少 pandoc 或 xelatex (需安裝 texlive-xetex)"
        except Exception as e:
            return False, f"文件轉 PDF 失敗: {e}"

    return False, f"不支援的檔案格式: {ext}"


def send_to_cups(pdf_path, printer_name, options=None):
    """
    送 PDF 到 CUPS 列印
    回傳 (success, job_id_or_error)
    """
    cfg = get_print_config()
    if options is None:
        options = {}

    # 建構 lp 參數
    lp_args = ["lp", "-d", printer_name]

    if cfg.get("fit_to_page"):
        lp_args.append("-o")
        lp_args.append("fit-to-page")

    media = options.get("media", cfg.get("media", "A4"))
    lp_args.extend(["-o", f"media={media}"])

    scaling = options.get("scaling", cfg.get("scaling", 90))
    lp_args.extend(["-o", f"scaling={scaling}"])

    copies = options.get("copies", 1)
    if copies > 1:
        lp_args.extend(["-n", str(copies)])

    lp_args.append(pdf_path)

    try:
        result = subprocess.run(lp_args, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            # 解析 job id: "request id is PrinterName-123 (1 file(s))"
            output = result.stdout.strip()
            if "request id is" in output:
                job_id = output.split("request id is")[1].split("(")[0].strip()
                return True, job_id
            return True, output
        else:
            return False, f"lp 失敗: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "列印指令逾時"
    except Exception as e:
        return False, f"列印錯誤: {e}"


def process_print_request(user_id, message_id, message_type, printer_hint=None, options=None):
    """
    處理完整列印流程：驗證權限 → 下載 → 轉 PDF → 列印
    回傳 (success, message_dict)
    """
    # 1. 檢查權限
    if not is_user_authorized(user_id):
        return False, {"error": "無列印權限，僅限管理員/操作人員"}

    # 2. 檢查功能是否啟用
    if not get_print_config().get("enabled", True):
        return False, {"error": "列印功能未啟用"}

    # 3. 下載內容
    success, temp_path, content_type = download_line_content(message_id, message_type)
    if not success:
        return False, {"error": temp_path}

    try:
        # 4. 轉 PDF
        success, pdf_path = convert_to_pdf(temp_path, content_type)
        if not success:
            return False, {"error": pdf_path, "temp_file": temp_path}

        # 5. 解析印表機
        printer = resolve_printer_name(printer_hint)

        # 6. 送列印
        success, result = send_to_cups(pdf_path, printer, options)
        if not success:
            return False, {"error": result, "pdf_file": pdf_path}

        return True, {
            "printer": printer,
            "job_id": result,
            "pdf_file": pdf_path,
            "original_file": temp_path,
        }

    finally:
        # 清理暫存檔（保留 PDF 供除錯，可選擇刪除）
        try:
            if temp_path != pdf_path and os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            pass


def test_print(printer_hint=None):
    """測試列印（產生簡單測試頁）"""
    from datetime import datetime
    cfg = get_print_config()
    printer = resolve_printer_name(printer_hint)

    # 產生測試內容（含中文）
    test_content = f"""LINE Monitor 測試列印
時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
印表機: {printer}
預設印表機: {cfg.get('default_printer')}
功能狀態: {'啟用' if cfg.get('enabled') else '停用'}

此為自動測試頁，確認列印功能正常。
中文測試：測試列印功能是否正常支援中文。"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(test_content)
        txt_path = f.name

    try:
        success, pdf_path = convert_to_pdf(txt_path, "text/plain")
        if not success:
            return False, pdf_path
        success, result = send_to_cups(pdf_path, printer)
        return success, {"printer": printer, "result": result}
    finally:
        try:
            os.unlink(txt_path)
        except Exception:
            pass
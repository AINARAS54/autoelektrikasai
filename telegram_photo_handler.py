import logging
from pathlib import Path

import requests

from photo_document_reader import analyze_vehicle_image, format_vehicle_image_result

logger = logging.getLogger("autoelektrikas_ai.telegram_photo")


def telegram_get_file(bot_token: str, file_id: str) -> dict | None:
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getFile"
        r = requests.post(url, json={"file_id": file_id}, timeout=20)
        if not r.ok:
            logger.error("Telegram getFile failed: %s %s", r.status_code, r.text)
            return None
        return r.json().get("result")
    except Exception:
        logger.exception("Telegram getFile exception")
        return None


def download_telegram_file(bot_token: str, file_path: str, local_path: Path) -> bool:
    try:
        url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        r = requests.get(url, timeout=60)
        if not r.ok:
            logger.error("Telegram file download failed: %s %s", r.status_code, r.text)
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(r.content)
        return True
    except Exception:
        logger.exception("Telegram file download exception")
        return False


def handle_photo_or_document(*, bot_token: str, message: dict, chat_id: str, base_dir: Path) -> dict:
    file_id = None
    filename = "upload.jpg"

    if message.get("photo"):
        file_id = message["photo"][-1].get("file_id")
        filename = f"{chat_id}_photo.jpg"

    elif message.get("document"):
        doc = message["document"]
        mime = doc.get("mime_type", "")
        if not (mime.startswith("image/") or mime == "application/pdf"):
            return {"handled": False, "text": "", "vision_result": None}
        file_id = doc.get("file_id")
        filename = doc.get("file_name") or f"{chat_id}_document"

    if not file_id:
        return {"handled": False, "text": "", "vision_result": None}

    file_info = telegram_get_file(bot_token, file_id)
    if not file_info or not file_info.get("file_path"):
        return {"handled": True, "text": "Nuotraukos nepavyko gauti iš Telegram.", "vision_result": None}

    local_path = base_dir / "uploads" / str(chat_id) / filename

    ok = download_telegram_file(bot_token, file_info["file_path"], local_path)
    if not ok:
        return {"handled": True, "text": "Nuotraukos nepavyko atsisiųsti.", "vision_result": None}

    result = analyze_vehicle_image(str(local_path))
    text = format_vehicle_image_result(result)

    return {
        "handled": True,
        "text": text,
        "vision_result": result,
        "local_path": str(local_path),
    }

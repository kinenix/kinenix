import logging
import math
from typing import Any, Dict, Optional, Tuple
import requests

from ..config import CENTRAL_LLM_URL

logger = logging.getLogger("kinenix.hub.ai")

CATEGORIES = {
    "Cookie Consent / Security Modal": {
        "th_label": "หน้าต่าง Cookie หรือการยืนยันสิทธิ์",
        "root_cause": "หน้าต่าง Cookie หรือป๊อปอัปความยินยอมไม่ปรากฏ หรือเคยถูกยอมรับไปแล้ว ทำให้ปุ่มเป้าหมายหายไปจากหน้าจอ",
        "suggestion": "ใช้ Action web.is_visible เพื่อตรวจสอบก่อนกด หรือใส่ optional: true ใน web.click"
    },
    "UI Selector Not Found / DOM Changed": {
        "th_label": "หาปุ่มหรือ Element ไม่พบบนหน้าเว็บ (โครงสร้างเปลี่ยน)",
        "root_cause": "Selector หรือ XPath ไม่ตรงกับโครงสร้าง HTML ปัจจุบันของเว็บไซต์",
        "suggestion": "ตรวจสอบ Selector ใน DevTools กับหน้าเว็บปัจจุบัน หรือรอให้ Element ปรากฏด้วย web.wait_for ก่อนใช้งาน"
    },
    "Page Load / Network Timeout": {
        "th_label": "เครือข่ายขัดข้อง หรือหน้าเว็บโหลดช้าเกินกำหนด",
        "root_cause": "เว็บไซต์ตอบสนองช้าเกินกว่าเวลา Timeout หรืออินเทอร์เน็ตขัดข้องระหว่างโหลดข้อมูล",
        "suggestion": "เพิ่ม timeout ใน web.wait_for หรือตั้งค่า max_retries: 2 ที่ step นั้น"
    },
    "File / Resource Missing": {
        "th_label": "ไม่พบไฟล์ที่จำเป็น (เช่น Excel หรือโฟลเดอร์)",
        "root_cause": "ไฟล์เป้าหมายไม่มีอยู่ในระบบ หรือระบุพาธผิดพลาด",
        "suggestion": "ตรวจสอบว่าสร้างไฟล์สำเร็จในขั้นตอนก่อนหน้า และพาธเป็น Relative Path ที่ถูกต้อง"
    },
    "Data Validation / Format Error": {
        "th_label": "ข้อมูลไม่ตรงรูปแบบ หรือตารางไม่มีข้อมูล",
        "root_cause": "ค่าที่ดึงมาได้จากหน้าเว็บว่างเปล่า หรือรูปแบบวันที่/ตัวเลขไม่ถูกต้อง",
        "suggestion": "ตรวจสอบข้อมูลของช่วงวันที่ที่เลือก หรือเพิ่มขั้นตอน logic.if ตรวจสอบค่าว่าง"
    },
}

# Not offered to the LLM: a Business error is decided by the flow itself (flow.fail), and Unknown is the
# honest answer when nothing matches, instead of guessing a selector problem
BUSINESS = {
    "th_label": "ข้อมูลไม่ผ่านกฎทางธุรกิจ (flow.fail)",
    "root_cause": "flow หยุดเองเพราะข้อมูลไม่ผ่านเงื่อนไขที่กำหนดไว้",
    "suggestion": "ตรวจข้อมูลต้นทางของรายการนี้ หรือแก้เงื่อนไขใน flow ถ้าเงื่อนไขไม่ถูกต้อง",
}
UNKNOWN = {
    "th_label": "ยังระบุสาเหตุไม่ได้",
    "root_cause": "ข้อความ error ไม่ตรงกับรูปแบบที่รู้จัก",
    "suggestion": "ดูข้อความ error และ step ที่ล้มด้วย kinenix hub logs หรือ kinenix hub report",
}

# Rule-based triage when the central LLM is not available: (words in the error, category), first match wins
RULES = (
    (("cookie", "consent"), "Cookie Consent / Security Modal"),
    (("filenotfound", "no such file", "file not found", "excel file not found", "path does not exist"), "File / Resource Missing"),
    (("timeout", "timed out", "net::err", "connection refused", "connectionerror"), "Page Load / Network Timeout"),
    (("selector", "locator", "xpath", "element not found", "no element", "strict mode violation"), "UI Selector Not Found / DOM Changed"),
    (("invalid literal", "could not convert", "valueerror", "does not match format", "empty table", "no rows"), "Data Validation / Format Error"),
)


def _rule_category(text: str) -> Optional[str]:
    lower = text.lower()
    for words, category in RULES:
        if any(word in lower for word in words):
            return category
    return None


def _llm_category(error_text: str, step: str) -> Optional[Tuple[str, float]]:
    """(category, confidence) from the central LLM, or None when it is unavailable or answers outside the list."""
    try:
        payload = {
            "type": "choice",
            "instructions": f"วิเคราะห์ประเภทของความผิดพลาดในระบบบอทอัตโนมัติจากข้อความ Error: '{error_text}' ที่ขั้นตอน: '{step}'",
            "criteria": {category: None for category in CATEGORIES},
        }
        res = requests.post(CENTRAL_LLM_URL, json=payload, timeout=5)
        data = res.json() if res.status_code == 200 else None
    except Exception as e:
        logger.warning(f"Central OpenThai server call failed, using rule-based triage: {e}")
        return None
    choice = data.get("choice") if isinstance(data, dict) else None
    if isinstance(choice, str) and choice in CATEGORIES:
        score = data.get("score")
        if score is None or isinstance(score, bool):
            return None
        try:
            confidence = float(score)
        except (TypeError, ValueError, OverflowError):
            return None
        if math.isfinite(confidence) and 0.0 <= confidence <= 1.0:
            return choice, confidence
    return None


def analyze_failure(
    flow_name: str,
    failed_step_name: Optional[str],
    error_message: Optional[str],
    exception_class: Optional[str] = None,
    error_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classifies a failed run and writes a short Thai summary. A Business error (flow.fail) is reported as
    such without asking the LLM; otherwise the central LLM decides, then word rules, and when neither
    knows, the answer is "unknown" rather than a guess.
    """
    err_text = error_message or ""
    step_desc = failed_step_name or "ไม่ระบุขั้นตอน"

    if (error_type or "").lower() == "business":
        meta, confidence = BUSINESS, 1.0
        reason = f"{meta['root_cause']}: {err_text}" if err_text else meta["root_cause"]
    else:
        found = _llm_category(err_text, step_desc)
        if found:
            meta, confidence = CATEGORIES[found[0]], found[1]
        else:
            category = _rule_category(f"{exception_class or ''} {err_text}")
            meta, confidence = (CATEGORIES[category], 0.6) if category else (UNKNOWN, 0.0)
        reason = meta["root_cause"]
        if meta is UNKNOWN and err_text:
            reason = f"{reason} ({err_text[:200]})"

    return {
        "category": meta["th_label"],
        "confidence": round(confidence * 100, 1),
        "summary": f"บอทไม่สามารถทำงานต่อได้ที่ขั้นตอน '{step_desc}' ของ Flow '{flow_name}' เนื่องจาก {reason}",
        "root_cause": meta["root_cause"],
        "suggestion": meta["suggestion"],
    }

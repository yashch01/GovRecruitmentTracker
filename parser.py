"""
parser.py — Zero-cost hybrid extraction pipeline for GovRecruitmentTracker.

Pipeline stages:
  Stage 1 (Local)   – pdfplumber text extraction + regex pre-filter (0 API cost).
  Stage 2 (AI)      – Gemini 2.5 Flash API on pages 1-3 only (free tier).
  Stage 3 (Offline) – Rule-based regex fallback (no API, never crashes).

Supporting classifiers:
  gov_classifier    – Government vs private domain/text check.
  age_verifier      – DOB + category → Eligible / Age Barred / Check Notice.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

# ── Optional pdfplumber import (graceful if missing) ─────────────────────────
try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

# ── Optional Gemini import ────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types as genai_types
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCANNED_PDF_THRESHOLD = 100          # chars; below this → scanned / image PDF

# CS/IT-specific degree / discipline keywords (high-confidence match)
_CS_IT_SPECIFIC = [
    r"computer\s+science",
    r"information\s+technology",
    r"b\.?\s*tech\b.*?\b(cse|cs|it)\b",
    r"b\.?\s*e\.?\b.*?\b(cse|cs|it)\b",
    r"m\.?\s*tech\b.*?\b(cse|cs|it|computer|information)",
    r"m\.?\s*sc\b.*?\b(computer|cs|it|information\s+technology)",
    r"mca\b",                         # MCA still supported as eligibility cue
    r"\bcs\s*/\s*it\b",
    r"\bcse\b",
    r"computer\s+engineer",
    r"software\s+engineer",
    r"it\s+officer",
    r"systems\s+engineer",
    r"data\s+scientist",
    r"cybersecurity",
    r"network\s+engineer",
    r"database\s+administrator",
    r"cloud\s+engineer",
    r"devops",
]

# Broad "any graduate" exam keywords (CS/IT BTech holder qualifies)
_ANY_GRADUATE = [
    r"any\s+graduate",
    r"graduation\s+in\s+any\s+discipline",
    r"bachelor[\u2019']?s?\s+degree\s+in\s+any",
    r"degree\s+in\s+any\s+discipline",
    r"graduate\s+in\s+any\s+stream",
    r"\bssc\s+cgl\b",
    r"\bssc\s+chsl\b",
    r"\bssc\s+(mts|gd|je|cpo|selection\s+post)\b",
    r"\bupsc\b",
    r"\bipas\b",
    r"\bcapf\b",
    r"\bibps\b",
    r"\bsbi\s+(po|clerk|so|probationary\s+officer)\b",
    r"\brbi\s+(grade|officer|assistant)\b",
    r"\bnabard\b",
    r"\bagniveer\b",
    r"\btes\b",                        # Technical Entry Scheme
    r"\bncc\s+(special\s+)?entry\b",
    r"army\s+(technical|engineering)",
    r"navy\s+technical",
    r"air\s+force\s+technical",
    r"indian\s+(army|navy|air\s+force)",
    r"central\s+government\s+(exam|recruitment|post)",
    r"group\s+[abc]\s+(post|service)",
]

# Hard-reject patterns: ONLY non-CS disciplines explicitly listed, no any-grad
_NON_CS_EXCLUSIVES = [
    r"\b(civil|mechanical|electrical|electronics|chemical|metallurgy|"
    r"agriculture|horticulture|geology|physics|chemistry|botany|zoology|"
    r"pharmacist|pharmacology|pharmacy|medical|medicine|nursing|"
    r"dental|veterinary|ayurvedic|homeopathic|library|law|"
    r"economics|finance|ca\b|chartered\s+accountant|"
    r"chartered\s+account|mbbs|bds|bams|b\.?pharmacy)\s+only\b",
]

# Gov domain whitelist
_GOV_DOMAINS = (
    ".gov.in", ".nic.in", ".res.in", ".ac.in",
    ".gov.in/", ".nic.in/",
    "upsc.gov", "ssc.gov", "ibps.in",
)

# Gov text indicators
_GOV_TEXT_PATTERNS = [
    r"central\s+government",
    r"govt\.\s+of\s+india",
    r"government\s+of\s+india",
    r"ministry\s+of\s+",
    r"\bpsu\b",
    r"public\s+sector\s+undertaking",
    r"autonomous\s+body\s+under\s+(meity|dst|drdo|dae|isro|dot|mha|moe)",
    r"\bdrdo\b",
    r"\bbarc\b",
    r"\bnielit\b",
    r"\bcdac\b",
    r"\bnil\b",
    r"\bnic\b",                        # National Informatics Centre
    r"\bbel\b",                        # Bharat Electronics
    r"\becil\b",
    r"\bbis\b",
    r"\bssc\b",
    r"\bupsc\b",
    r"\bibps\b",
    r"staff\s+selection\s+commission",
    r"union\s+public\s+service\s+commission",
    r"scheduled\s+bank",
    r"nationalised\s+bank",
]

# Indian date patterns (DD/MM/YYYY, DD-MM-YYYY, DDth Month YYYY, YYYY-MM-DD)
_DATE_PATTERNS = [
    r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})\b",
    r"\b(\d{1,2})\s*(st|nd|rd|th)?\s+"
    r"(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s*,?\s*(\d{4})\b",
    r"\b(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\b",
]

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Pay level patterns (7th CPC Pay Matrix + CTC)
_PAY_PATTERNS = [
    r"pay\s+level[-\s]+(\d+)",
    r"level[-\s]+(\d+)\s+(?:of\s+)?(?:the\s+)?pay\s+matrix",
    r"₹\s*(\d{2,3},\d{3})\s*[-–]\s*(?:₹\s*)?(\d{2,3},\d{3})",
    r"rs\.?\s*(\d{2,3},\d{3})\s*[-–]\s*(?:rs\.?\s*)?(\d{2,3},\d{3})",
    r"(\d{2,3},\d{3})\s*(?:p\.?m\.?|per\s+month)",
    r"ctc\s*(?:of\s+)?(?:rs\.?|₹)?\s*([\d,]+\s*(?:lpa|lakhs?|lakh))",
]

_PAY_LEVEL_SALARY = {
    1: "₹18,000", 2: "₹19,900", 3: "₹21,700", 4: "₹25,500",
    5: "₹29,200", 6: "₹35,400", 7: "₹44,900", 8: "₹47,600",
    9: "₹53,100", 10: "₹56,100", 11: "₹67,700", 12: "₹78,800",
    13: "₹1,23,100", 14: "₹1,44,200",
}

# GATE keywords
_GATE_REQUIRED = [
    r"valid\s+gate\s+score",
    r"gate\s+qualified",
    r"gate\s+score\s+(?:is\s+)?(?:mandatory|essential|required)",
    r"through\s+gate",
    r"gate\s+\d{4}",
]
_GATE_NOT_REQUIRED = [
    r"without\s+gate",
    r"non[-\s]*gate",
    r"no\s+gate",
    r"gate\s+(?:score\s+)?(?:not\s+required|not\s+mandatory|not\s+needed)",
    r"direct\s+recruitment",
    r"written\s+test",                 # own exam, not GATE
]

# Age limit patterns
_AGE_PATTERNS = [
    r"(?:maximum\s+)?age\s+(?:limit\s+)?(?:is\s+)?(\d{2})\s*years?",
    r"not\s+(?:more\s+than|exceeding)\s+(\d{2})\s*years?",
    r"below\s+(\d{2})\s*years?",
    r"up\s+to\s+(\d{2})\s*years?",
    r"(?:max|maximum)\s+(\d{2})\s*years?",
    r"between\s+(\d{2})\s*(?:and|to)\s+(\d{2})\s*years?",
    r"(\d{2})\s*[-–]\s*(\d{2})\s*years?",
    r"age\s*:\s*(\d{2})\s*years?",
]

# Age-limit cutoff date patterns
_CUTOFF_PATTERNS = [
    r"as\s+(?:on|of)\s+(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})",
    r"as\s+(?:on|of)\s+(\d{1,2})\s*(st|nd|rd|th)?\s+"
    r"(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s*,?\s*(\d{4})",
    r"reckoned\s+as\s+on\s+(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})",
]

# Age relaxations by category (in years, per Indian Govt rules)
_AGE_RELAXATION = {
    "OBC": 3,
    "SC": 5,
    "ST": 5,
    "EWS": 0,
    "General": 0,
}

# Selection process keywords
_SELECTION_PATTERNS = {
    "Written Exam":       r"written\s+(?:test|exam|examination)",
    "CBT":                r"\bcbt\b|computer\s+based\s+test",
    "GATE Score":         r"gate\s+score",
    "Interview":          r"\binterview\b",
    "Skill Test":         r"skill\s+test|typing\s+test",
    "Document Verification": r"document\s+(?:verification|veri\.?)",
    "Negative Marking":   r"negative\s+mark",
    "Merit List":         r"merit\s+list|merit[-\s]based",
    "Walk-in":            r"walk[-\s]in",
}


# ===========================================================================
# PDF Text Extraction
# ===========================================================================

def extract_text_from_pdf(pdf_path: str, max_pages: int = 3) -> dict[str, Any]:
    """
    Extract text from a PDF using pdfplumber (Stage 1 local extraction).

    Returns:
        {
          "text": str,
          "char_count": int,
          "page_count": int,
          "pages_extracted": int,
          "is_scanned": bool,   # True if char_count < SCANNED_PDF_THRESHOLD
          "error": str | None,
        }
    """
    result: dict[str, Any] = {
        "text": "",
        "char_count": 0,
        "page_count": 0,
        "pages_extracted": 0,
        "is_scanned": False,
        "error": None,
    }

    if not _PDFPLUMBER_AVAILABLE:
        result["error"] = "pdfplumber not installed"
        return result

    if not Path(pdf_path).exists():
        result["error"] = f"File not found: {pdf_path}"
        return result

    try:
        with pdfplumber.open(pdf_path) as pdf:
            result["page_count"] = len(pdf.pages)
            pages_to_read = pdf.pages[:max_pages]
            texts = []
            for page in pages_to_read:
                page_text = page.extract_text() or ""
                texts.append(page_text)
                result["pages_extracted"] += 1
            result["text"] = "\n".join(texts)
            result["char_count"] = len(result["text"].strip())
            result["is_scanned"] = result["char_count"] < SCANNED_PDF_THRESHOLD
    except Exception as exc:
        result["error"] = str(exc)
        result["is_scanned"] = True   # treat as scanned if unreadable

    return result


# ===========================================================================
# Stage 1 — CS/IT Eligibility Pre-Filter
# ===========================================================================

def _match_any(text: str, patterns: list[str]) -> bool:
    """Return True if any pattern matches in text (case-insensitive)."""
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def is_eligible_for_cs_it_holder(text: str) -> dict[str, Any]:
    """
    Stage 1 pre-filter. Decides whether a CS/IT BTech holder can apply.

    Returns:
        {
          "eligible": bool,       # True → proceed to Stage 2/3
          "match_type": str,      # "cs_it_specific" | "any_graduate" | "none"
          "confidence": str,      # "high" | "medium" | "low"
          "reason": str,
        }
    """
    # Step A: Check hard-exclusion (only non-CS disciplines mentioned)
    has_cs_it     = _match_any(text, _CS_IT_SPECIFIC)
    has_any_grad  = _match_any(text, _ANY_GRADUATE)
    has_exclusive_non_cs = _match_any(text, _NON_CS_EXCLUSIVES)

    if has_cs_it:
        return {
            "eligible": True,
            "match_type": "cs_it_specific",
            "confidence": "high",
            "reason": "CS/IT-specific discipline explicitly mentioned.",
        }

    if has_any_grad:
        # Even if non-CS also mentioned, any-grad means CS/IT holder qualifies
        return {
            "eligible": True,
            "match_type": "any_graduate",
            "confidence": "medium",
            "reason": "Open to any graduate — CS/IT BTech holders qualify.",
        }

    if has_exclusive_non_cs:
        return {
            "eligible": False,
            "match_type": "none",
            "confidence": "high",
            "reason": "Exclusively requires non-CS discipline; CS/IT holders ineligible.",
        }

    # No strong signal either way → drop to avoid noise
    return {
        "eligible": False,
        "match_type": "none",
        "confidence": "low",
        "reason": "No CS/IT or any-graduate keywords detected.",
    }


# ===========================================================================
# Government vs Private Classifier
# ===========================================================================

def classify_gov(url: str = "", text: str = "") -> dict[str, Any]:
    """
    Determine if a recruitment is from a government/PSU body.

    Returns:
        {
          "is_gov": bool,
          "confidence": str,
          "reason": str,
        }
    """
    url_lower = url.lower()

    # URL domain whitelist (strongest signal)
    for domain in _GOV_DOMAINS:
        if domain in url_lower:
            return {
                "is_gov": True,
                "confidence": "high",
                "reason": f"URL contains government domain: {domain}",
            }

    # Text-based signals
    if _match_any(text, _GOV_TEXT_PATTERNS):
        return {
            "is_gov": True,
            "confidence": "medium",
            "reason": "Government organization keyword found in notice text.",
        }

    # Known private job board domains → reject
    private_domains = (
        "naukri.com", "linkedin.com", "indeed.com", "shine.com",
        "monster.com", "timesjobs.com", "foundit.in", "glassdoor.com",
    )
    for domain in private_domains:
        if domain in url_lower:
            return {
                "is_gov": False,
                "confidence": "high",
                "reason": f"URL is a private job portal: {domain}",
            }

    return {
        "is_gov": False,
        "confidence": "low",
        "reason": "No government indicators found.",
    }


# ===========================================================================
# Stage 2 — Gemini Flash AI Extractor
# ===========================================================================

_GEMINI_PROMPT_TEMPLATE = """
You are an expert at parsing Indian government recruitment notifications.
Extract the following structured information from the notice text provided.
Respond ONLY with valid JSON — no markdown, no explanation.

Notice organization hint: {org_name}

Fields to extract:
- title: Post/Position name (string)
- organization: Hiring organization (string)
- pay_level_or_ctc: Pay level or CTC (e.g. "Level 10 (₹56,100-₹1,77,500)" or "₹12 LPA") (string)
- gate_required: Is a valid GATE score mandatory? (boolean)
- start_date: Application start date in DD/MM/YYYY format (string, empty if unknown)
- last_date: Last date to apply / registration deadline in DD/MM/YYYY format (string, empty if unknown)
- fee_last_date: Last date for fee payment in DD/MM/YYYY format (string, empty if unknown)
- exam_date: Examination date in DD/MM/YYYY format (string, empty if unknown)
- age_limit_details: Age limit details (e.g. "Max 30 years as on 01/01/2025") (string)
- selection_summary: Short summary of selection process (e.g. "Written Exam → Interview, Negative marking applies") (string)
- exam_category: One of: "Technical CS/IT", "Competitive Exam", "PSU", "Military", "Banking", "Other" (string)
- is_cs_it: Is this specifically for CS/IT discipline? (boolean)
- any_graduate_eligible: Is any graduate (including CS/IT BTech) eligible? (boolean)
- vacancies: Total number of vacancies if mentioned (integer or null)

Notice text (first 3 pages):
---
{notice_text}
---
"""

_STRUCTURED_SCHEMA = {
    "type": "object",
    "properties": {
        "title":               {"type": "string"},
        "organization":        {"type": "string"},
        "pay_level_or_ctc":    {"type": "string"},
        "gate_required":       {"type": "boolean"},
        "start_date":          {"type": "string"},
        "last_date":           {"type": "string"},
        "fee_last_date":       {"type": "string"},
        "exam_date":           {"type": "string"},
        "age_limit_details":   {"type": "string"},
        "selection_summary":   {"type": "string"},
        "exam_category":       {"type": "string"},
        "is_cs_it":            {"type": "boolean"},
        "any_graduate_eligible": {"type": "boolean"},
        "vacancies":           {"type": ["integer", "null"]},
    },
    "required": [
        "title", "organization", "gate_required",
        "last_date", "exam_category", "is_cs_it", "any_graduate_eligible",
    ],
}


def extract_with_gemini(
    text: str,
    org_name: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    """
    Stage 2: Extract structured job data using Gemini 2.5 Flash API.

    Returns extracted dict on success, or {"_error": str} on failure.
    Caller should fall back to Stage 3 on any error.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "")

    if not api_key:
        return {"_error": "GEMINI_API_KEY not set — using offline fallback."}

    if not _GENAI_AVAILABLE:
        return {"_error": "google-genai not installed."}

    try:
        client = genai.Client(api_key=api_key)
        prompt = _GEMINI_PROMPT_TEMPLATE.format(
            org_name=org_name or "Unknown Organization",
            notice_text=text[:8000],      # hard cap to stay within free-tier limits
        )
        gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        response = client.models.generate_content(
            model=gemini_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        raw = (response.text or "").strip()
        # Strip markdown fences if model wraps response
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)
        data["_source"] = "gemini"
        return data

    except json.JSONDecodeError as exc:
        return {"_error": f"JSON parse error: {exc}"}
    except Exception as exc:
        return {"_error": f"Gemini API error: {exc}"}


# ===========================================================================
# Stage 3 — Offline Regex Fallback
# ===========================================================================

def _extract_dates_from_text(text: str) -> list[str]:
    """Extract all date strings from text, return as DD/MM/YYYY."""
    found = []
    # Pattern 1: DD/MM/YYYY or DD-MM-YYYY
    for m in re.finditer(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})\b", text):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        found.append(f"{d.zfill(2)}/{mo.zfill(2)}/{y}")
    # Pattern 2: DD Month YYYY
    for m in re.finditer(
        r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+"
        r"(january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\s*,?\s*(\d{4})\b",
        text, re.IGNORECASE
    ):
        d   = m.group(1).zfill(2)
        mo  = str(_MONTH_MAP.get(m.group(2).lower(), 0)).zfill(2)
        y   = m.group(3)
        if mo != "00":
            found.append(f"{d}/{mo}/{y}")
    # Pattern 3: YYYY-MM-DD
    for m in re.finditer(r"\b(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\b", text):
        y, mo, d = m.group(1), m.group(2), m.group(3)
        found.append(f"{d.zfill(2)}/{mo.zfill(2)}/{y}")
    return found


def _extract_pay(text: str) -> str:
    """Extract pay level or CTC from text."""
    # Try pay level first (most specific)
    m = re.search(r"pay\s+level[-\s]+(\d+)", text, re.IGNORECASE)
    if not m:
        m = re.search(r"level[-\s]+(\d+)\s+(?:of\s+)?(?:the\s+)?pay\s+matrix", text, re.IGNORECASE)
    if m:
        lvl = int(m.group(1))
        salary = _PAY_LEVEL_SALARY.get(lvl, "")
        suffix = f" ({salary}+)" if salary else ""
        return f"Level {lvl}{suffix}"

    # Try rupee range
    m = re.search(
        r"(?:₹|rs\.?)\s*([\d,]+)\s*[-–]\s*(?:₹|rs\.?)?\s*([\d,]+)",
        text, re.IGNORECASE
    )
    if m:
        return f"₹{m.group(1)} – ₹{m.group(2)}"

    # Try CTC
    m = re.search(
        r"ctc\s*(?:of\s+)?(?:rs\.?|₹)?\s*([\d,]+\s*(?:lpa|lakhs?|lakh))",
        text, re.IGNORECASE
    )
    if m:
        return f"CTC ₹{m.group(1)}"

    return ""


def _detect_gate(text: str) -> bool:
    """Return True if GATE score is mandatory."""
    if _match_any(text, _GATE_NOT_REQUIRED):
        return False
    return _match_any(text, _GATE_REQUIRED)


def _extract_age_limit(text: str) -> str:
    """Extract age limit string from text."""
    for pat in _AGE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            groups = [g for g in m.groups() if g and g.isdigit()]
            if len(groups) == 2:
                return f"{groups[0]}–{groups[1]} years"
            if groups:
                return f"Max {groups[0]} years"
    return ""


def _extract_cutoff_date(text: str) -> str | None:
    """Extract the age-limit cutoff date (as on DD/MM/YYYY)."""
    for pat in _CUTOFF_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            groups = m.groups()
            if len(groups) >= 3 and groups[2].isdigit() and len(groups[2]) == 4:
                # DD/MM/YYYY style
                return f"{groups[0].zfill(2)}/{groups[1].zfill(2)}/{groups[2]}"
            if len(groups) >= 4:
                # DD Month YYYY style
                mo = str(_MONTH_MAP.get(str(groups[2]).lower(), 0)).zfill(2)
                if mo != "00":
                    return f"{groups[0].zfill(2)}/{mo}/{groups[3]}"
    return None


def _extract_selection_summary(text: str) -> str:
    """Build a short selection process summary."""
    parts = []
    for label, pat in _SELECTION_PATTERNS.items():
        if re.search(pat, text, re.IGNORECASE):
            parts.append(label)
    return " → ".join(parts) if parts else "See notification"


def _infer_exam_category(text: str, url: str = "") -> str:
    """Infer exam category from text and URL signals."""
    combined = (text + " " + url).lower()
    if re.search(r"\b(ibps|sbi|rbi|nabard|bank)\b", combined):
        return "Banking"
    if re.search(r"\b(agniveer|tes\b|ncc\s+entry|army|navy|air\s+force)\b", combined):
        return "Military"
    if re.search(r"\bupsc\b|union\s+public\s+service", combined):
        return "Competitive Exam"
    if re.search(r"\bssc\b|staff\s+selection", combined):
        return "Competitive Exam"
    # PSU: named PSUs in URL or text (expanded list)
    if re.search(
        r"\b(drdo|barc|rac\b|nielit|cdac|ecil|bel\b|bis\b|bhel|ongc|ntpc|gail|sail|"
        r"coal\s*india|hal\b|nalco|mecon|concor|irctc|powergrid|nhpc|neepco)\b",
        combined
    ):
        return "PSU"
    # Technical bodies that are not primarily PSU
    if re.search(r"\b(nic\b|nielit|isro|insa|csir)\b", combined):
        return "Technical CS/IT"
    if re.search(r"public\s+sector|psu\b|undertaking", combined):
        return "PSU"
    return "Other"


def extract_with_regex(text: str, url: str = "") -> dict[str, Any]:
    """
    Stage 3: Offline regex-based extraction. Never throws — always returns a dict.

    Returns:
        dict with same keys as extract_with_gemini (minus _source="regex")
    """
    dates = _extract_dates_from_text(text)
    age_str = _extract_age_limit(text)
    cutoff  = _extract_cutoff_date(text)
    age_details = age_str
    if cutoff:
        age_details += f" as on {cutoff}" if age_str else f"Cutoff: {cutoff}"

    cs_it_check = is_eligible_for_cs_it_holder(text)
    gate = _detect_gate(text)
    pay  = _extract_pay(text)
    selection = _extract_selection_summary(text)
    category  = _infer_exam_category(text, url)

    # Heuristic date assignment:
    # "last date", "closing date", "apply before" → last_date
    last_date = ""
    start_date = ""
    fee_last_date = ""
    exam_date = ""

    # Look for contextual date labels
    ld_m = re.search(
        r"(?:last\s+date|closing\s+date|apply\s+before|submit\s+(?:application|form)(?:\s+before)?)"
        r"[^0-9]{0,50}(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{4})",
        text, re.IGNORECASE
    )
    if ld_m:
        raw = ld_m.group(1)
        parts = re.split(r"[\/\-\.]", raw)
        if len(parts) == 3:
            last_date = f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}"

    sd_m = re.search(
        r"(?:start(?:ing)?\s+date|opening\s+date|registration\s+(?:start|begin|open))"
        r"[^0-9]{0,50}(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{4})",
        text, re.IGNORECASE
    )
    if sd_m:
        raw = sd_m.group(1)
        parts = re.split(r"[\/\-\.]", raw)
        if len(parts) == 3:
            start_date = f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}"

    fee_m = re.search(
        r"(?:fee\s+(?:payment\s+)?last\s+date|last\s+date\s+(?:for|of)\s+fee)"
        r"[^0-9]{0,50}(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{4})",
        text, re.IGNORECASE
    )
    if fee_m:
        raw = fee_m.group(1)
        parts = re.split(r"[\/\-\.]", raw)
        if len(parts) == 3:
            fee_last_date = f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}"

    exam_m = re.search(
        r"(?:exam(?:ination)?\s+date|written\s+test\s+(?:date|on)|exam\s+on|tentative\s+date\s+of\s+exam)"
        r"[^0-9]{0,50}(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{4})",
        text, re.IGNORECASE
    )
    if exam_m:
        raw = exam_m.group(1)
        parts = re.split(r"[\/\-\.]", raw)
        if len(parts) == 3:
            exam_date = f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}"

    # Fallback: use first detected date as last_date if none found contextually
    if not last_date and dates:
        last_date = dates[0]

    return {
        "title":               "",            # Cannot reliably extract from regex alone
        "organization":        "",
        "pay_level_or_ctc":    pay,
        "gate_required":       gate,
        "start_date":          start_date,
        "last_date":           last_date,
        "fee_last_date":       fee_last_date,
        "exam_date":           exam_date,
        "age_limit_details":   age_details,
        "selection_summary":   selection,
        "exam_category":       category,
        "is_cs_it":            cs_it_check["match_type"] == "cs_it_specific",
        "any_graduate_eligible": cs_it_check["match_type"] == "any_graduate",
        "vacancies":           None,
        "_source":             "regex",
        "_all_dates_found":    dates,         # debug: all dates detected
    }


# ===========================================================================
# Full Pipeline Runner
# ===========================================================================

def run_extraction_pipeline(
    text: str = "",
    url: str = "",
    org_name: str = "",
    api_key: str = "",
    raw_text: str = "",
    pdf_path: str | None = None,
    gemini_api_key: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Run the full extraction pipeline (Stage 2 → Stage 3 fallback).

    Supports text or pdf_path, and both api_key and gemini_api_key.
    Assumes Stage 1 pre-filter has already passed before calling this.
    """
    effective_text = text or raw_text
    effective_key = api_key or gemini_api_key

    if not effective_text and pdf_path and Path(pdf_path).exists():
        pdf_res = extract_text_from_pdf(pdf_path)
        effective_text = pdf_res.get("text", "")

    # Try Stage 2 first
    result = extract_with_gemini(effective_text, org_name=org_name, api_key=effective_key)

    if "_error" in result:
        # Graceful fallback to Stage 3
        fallback = extract_with_regex(effective_text, url=url)
        fallback["_fallback_reason"] = result["_error"]
        return fallback

    return result


# ===========================================================================
# Age Verifier
# ===========================================================================

def _parse_date_str(date_str: str) -> date | None:
    """Parse DD/MM/YYYY or YYYY-MM-DD string to a date object."""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def verify_age_eligibility(
    user_dob: str,
    user_category: str,
    age_limit_details: str,
) -> dict[str, Any]:
    """
    Verify age eligibility for a recruitment notice.

    Args:
        user_dob:         DOB string in YYYY-MM-DD or DD/MM/YYYY format.
        user_category:    One of General, OBC, SC, ST, EWS.
        age_limit_details: Raw string from the notice (e.g. "Max 30 years as on 01/08/2025").

    Returns:
        {
          "result": "Eligible" | "Age Barred" | "Check Notice",
          "user_age_on_cutoff": int | None,
          "max_age_allowed": int | None,
          "cutoff_date": str | None,
          "relaxation_applied": int,
          "reason": str,
        }
    """
    if not user_dob or not age_limit_details:
        return {
            "result": "Check Notice",
            "user_age_on_cutoff": None,
            "max_age_allowed": None,
            "cutoff_date": None,
            "relaxation_applied": 0,
            "reason": "DOB or age limit details missing.",
        }

    dob = _parse_date_str(user_dob)
    if dob is None:
        return {
            "result": "Check Notice",
            "user_age_on_cutoff": None,
            "max_age_allowed": None,
            "cutoff_date": None,
            "relaxation_applied": 0,
            "reason": f"Could not parse DOB: {user_dob}",
        }

    # Extract max age from details string
    max_age = None
    m = re.search(r"(\d{2})\s*(?:–|-|to)\s*(\d{2})\s*years?", age_limit_details, re.IGNORECASE)
    if m:
        max_age = int(m.group(2))     # upper bound of range
    else:
        m = re.search(r"(?:max(?:imum)?|up\s+to|below|not\s+(?:more\s+than|exceeding))?\s*(\d{2})\s*years?",
                      age_limit_details, re.IGNORECASE)
        if m:
            max_age = int(m.group(1))

    if max_age is None:
        return {
            "result": "Check Notice",
            "user_age_on_cutoff": None,
            "max_age_allowed": None,
            "cutoff_date": None,
            "relaxation_applied": 0,
            "reason": "Could not parse max age from notice.",
        }

    # Apply category relaxation
    relaxation = _AGE_RELAXATION.get(user_category, 0)
    effective_max_age = max_age + relaxation

    # Determine cutoff date
    cutoff_str = _extract_cutoff_date(age_limit_details)
    if cutoff_str:
        cutoff = _parse_date_str(cutoff_str)
    else:
        cutoff = date.today()        # fallback: use today
        cutoff_str = cutoff.isoformat()

    if cutoff is None:
        cutoff = date.today()
        cutoff_str = cutoff.isoformat()

    # Calculate age on cutoff date
    user_age = (
        cutoff.year - dob.year
        - ((cutoff.month, cutoff.day) < (dob.month, dob.day))
    )

    if user_age <= effective_max_age:
        result_label = "Eligible"
        reason = (
            f"Age {user_age} yrs ≤ Max {effective_max_age} yrs "
            f"(base {max_age} + {relaxation} yr {user_category} relaxation) "
            f"on {cutoff_str}."
        )
    else:
        result_label = "Age Barred"
        reason = (
            f"Age {user_age} yrs > Max {effective_max_age} yrs "
            f"(base {max_age} + {relaxation} yr {user_category} relaxation) "
            f"on {cutoff_str}."
        )

    return {
        "result": result_label,
        "user_age_on_cutoff": user_age,
        "max_age_allowed": effective_max_age,
        "cutoff_date": cutoff_str,
        "relaxation_applied": relaxation,
        "reason": reason,
    }


# ===========================================================================
# PARSER_REGISTRY — plugin slot for future custom parsers
# ===========================================================================

PARSER_REGISTRY: dict[str, Any] = {
    "regex":  extract_with_regex,
    "gemini": extract_with_gemini,
    # Future: "spacy": extract_with_spacy, "openai": extract_with_openai, …
}


if __name__ == "__main__":
    # Quick smoke test
    sample = (
        "DRDO RAC invites applications for the post of Scientist 'B' "
        "in Computer Science & Engineering. Eligibility: B.Tech CSE/IT. "
        "GATE score in CS/IT is mandatory. Pay: Level 10 (₹56,100 - ₹1,77,500). "
        "Last date to apply: 15/10/2025. Age limit: Max 28 years as on 01/08/2025."
    )
    print("=== Stage 1 pre-filter ===")
    print(is_eligible_for_cs_it_holder(sample))
    print("\n=== Gov classifier ===")
    print(classify_gov(url="https://rac.gov.in/notification", text=sample))
    print("\n=== Stage 3 Regex Fallback ===")
    print(json.dumps(extract_with_regex(sample), indent=2))
    print("\n=== Age Verifier ===")
    print(verify_age_eligibility("1998-04-15", "OBC", "Max 28 years as on 01/08/2025"))

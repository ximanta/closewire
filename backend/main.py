"""
Program Counselling Arena
URL-grounded analysis + Gemini-powered streamed negotiation.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import queue
import random
import re
import threading
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.protobuf.json_format import MessageToDict
from google import genai
from google.genai import types
from pydantic import BaseModel, HttpUrl
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from typing_extensions import TypedDict
from xml.sax.saxutils import escape as xml_escape

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("negotiation-arena")

load_dotenv()


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_NEGOTIATION_MAX_ROUNDS = _env_int("NEGOTIATION_MAX_ROUNDS", 10, 1, 50)
NEGOTIATION_MAX_ROUNDS_LIMIT = _env_int("NEGOTIATION_MAX_ROUNDS_LIMIT", 20, 1, 100)
AUTH_TOKEN_TTL_SECONDS = _env_int("AUTH_TOKEN_TTL_SECONDS", 43200, 60, 604800)
NEGOTIATION_DEBUG_TRACE = _env_bool("NEGOTIATION_DEBUG_TRACE", True)
NEGOTIATION_STREAM_CONSOLE_LOG = _env_bool("NEGOTIATION_STREAM_CONSOLE_LOG", True)
NEGOTIATION_STREAM_IDLE_TIMEOUT_SECONDS = _env_int("NEGOTIATION_STREAM_IDLE_TIMEOUT_SECONDS", 25, 5, 120)

app = FastAPI(title="AI Negotiation Arena")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _configure_models() -> Tuple[genai.Client, str, str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    negotiation_model_name = os.getenv("GEMINI_MODEL", "").strip()
    if not negotiation_model_name:
        raise RuntimeError("GEMINI_MODEL is not set")
    judge_model_name = os.getenv("GEMINI_JUDGE_MODEL", negotiation_model_name)
    client = genai.Client(api_key=api_key)
    return client, negotiation_model_name, judge_model_name


CLIENT: Optional[genai.Client] = None
NEGOTIATION_MODEL_NAME: Optional[str] = None
JUDGE_MODEL_NAME: Optional[str] = None


def get_client_and_models() -> Tuple[genai.Client, str, str]:
    global CLIENT, NEGOTIATION_MODEL_NAME, JUDGE_MODEL_NAME
    if CLIENT is None or NEGOTIATION_MODEL_NAME is None or JUDGE_MODEL_NAME is None:
        CLIENT, NEGOTIATION_MODEL_NAME, JUDGE_MODEL_NAME = _configure_models()
    return CLIENT, NEGOTIATION_MODEL_NAME, JUDGE_MODEL_NAME


ARCHETYPE_LABELS: Dict[str, str] = {
    "desperate_switcher": "Desperate Switcher",
    "skeptical_shopper": "Skeptical Shopper",
    "stagnant_pro": "Stagnant Pro",
    "credential_hunter": "Credential Hunter",
    "fomo_victim": "FOMO Victim",
    "drifter": "Drifter",
    "intellectual_buyer": "Intellectual Buyer",
    "car_buyer": "Car Buyer",
    "discount_hunter": "Discount Hunter",
}

ARCHETYPE_CONFIGS: Dict[str, Dict[str, str]] = {
    "desperate_switcher": {
        "core_drive": "Security & Job Guarantee",
        "stress_trigger": "Technical complexity or vague answers",
        "emotional_response": "Panic, begging for reassurance, self-doubt",
        "language_instruction": "Indian Academic English. Use 'Sir/Ma'am' often and terms like Batch, Passing out, Gap, Scope.",
    },
    "skeptical_shopper": {
        "core_drive": "Value for Money & Trust",
        "stress_trigger": "Sales talk or hidden terms",
        "emotional_response": "Suspicion, aggression, comparing with competitors",
        "language_instruction": "Natural Hindi only (Devanagari). No Hinglish or English code-mixing.",
    },
    "stagnant_pro": {
        "core_drive": "Efficiency, ROI & Status",
        "stress_trigger": "Being treated like a beginner or wasting time",
        "emotional_response": "Arrogance, impatience, condescension",
        "language_instruction": "Corporate Indian English. Use terms like Bandwidth, Relevant, Upskill, Package hike.",
    },
    "credential_hunter": {
        "core_drive": "CV Brand Value & Accreditation",
        "stress_trigger": "Learning heavy concepts without certificate focus",
        "emotional_response": "Detachment, transactional checking of boxes",
        "language_instruction": "Formal/Bureaucratic language. Ask about Validity, Hard copy, HR recognition.",
    },
    "drifter": {
        "core_drive": "Ease of Effort & Shortcuts",
        "stress_trigger": "Hard work, mandatory attendance, strict projects",
        "emotional_response": "Apathy, looking for loopholes",
        "language_instruction": "Passive Indian English. Ask about attendance, minimum marks, easy or tough.",
    },
    "fomo_victim": {
        "core_drive": "Speed & Trendiness (AI/GenAI)",
        "stress_trigger": "Foundational topics (Math/SQL) or long duration",
        "emotional_response": "Boredom, distraction, shallow impatience",
        "language_instruction": "Buzzword-heavy style with terms like ChatGPT, Prompt Engineering, Trending, Viral.",
    },
    "intellectual_buyer": {
        "core_drive": "Subject Matter Mastery & Curriculum Depth",
        "stress_trigger": (
            "Vague outcomes, buzzwords without mechanism, skipped prerequisites, "
            "or claims lacking technical proof and implementation detail"
        ),
        "emotional_response": (
            "Analytical, probing, and exacting; challenges assumptions; "
            "asks layered follow-ups until depth and boundaries are explicit"
        ),
        "language_instruction": (
            "Technical, precise, and mechanism-first. Prefer 'how/which/why' questions. "
            "Ask for specific tools, frameworks, architecture choices, trade-offs, "
            "evaluation methodology, and expected depth by module."
        ),
    },
    "car_buyer": {
        "core_drive": "Reliability, Status & Features",
        "stress_trigger": "Hidden costs, aggressive upselling, or lack of clear specifications",
        "emotional_response": "Negotiation-focused, skeptical of dealership tactics, comparing alternatives",
        "language_instruction": "Conversational, asking about mileage, warranty, on-road prices, and financing.",
    },
    "discount_hunter": {
        "core_drive": "Maximum Savings & Freebies",
        "stress_trigger": "High processing fees or rigid pricing",
        "emotional_response": "Relentless, comparing with every competitor, walking away early",
        "language_instruction": "Direct, focused on discounts, corporate loyalty, exchange bonuses, and referral benefits.",
    },
}

PERSONA_VOICE_CATALOG_FILE = Path(__file__).resolve().parent / "config" / "persona_voice_catalog.json"
PERSONA_IDENTITY_CATALOG: Optional[Dict[str, Any]] = None


def _load_persona_identity_catalog() -> Dict[str, Any]:
    global PERSONA_IDENTITY_CATALOG
    if PERSONA_IDENTITY_CATALOG is not None:
        return PERSONA_IDENTITY_CATALOG
    fallback = {
        "default": {
            "male": ["Aman", "Saurabh", "Nikhil", "Rahul", "Rohan", "Rajesh", "Arjun", "Karan"],
            "female": ["Riya", "Neha", "Anjali", "Priya", "Sana", "Kavya", "Pooja", "Shruti"],
        },
        "archetype_overrides": {},
    }
    try:
        if PERSONA_VOICE_CATALOG_FILE.exists():
            parsed = json.loads(PERSONA_VOICE_CATALOG_FILE.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                fallback.update(parsed)
    except Exception:
        logger.exception("Failed to load persona voice catalog from %s", PERSONA_VOICE_CATALOG_FILE)
    PERSONA_IDENTITY_CATALOG = fallback
    return PERSONA_IDENTITY_CATALOG


def _pick_persona_identity(archetype_id: str) -> Tuple[str, str]:
    catalog = _load_persona_identity_catalog()
    overrides = catalog.get("archetype_overrides", {}) if isinstance(catalog, dict) else {}
    default = catalog.get("default", {}) if isinstance(catalog, dict) else {}
    source = overrides.get(archetype_id) if isinstance(overrides, dict) else None
    if not isinstance(source, dict):
        source = default if isinstance(default, dict) else {}

    male_names = [str(x).strip() for x in (source.get("male") or []) if str(x).strip()]
    female_names = [str(x).strip() for x in (source.get("female") or []) if str(x).strip()]
    if not male_names:
        male_names = ["Aman", "Rahul", "Rohan", "Rajesh"]
    if not female_names:
        female_names = ["Riya", "Neha", "Anjali", "Priya"]

    gender = random.choice(["male", "female"])
    name = random.choice(male_names if gender == "male" else female_names)
    return name, gender


class ProgramSummary(TypedDict):
    program_name: str
    value_proposition: str
    key_features: List[str]
    target_audience: str
    positioning_angle: str
    duration: str
    format: str
    weekly_time_commitment: str
    program_fee_inr: str
    placement_support_details: str
    certification_details: str
    curriculum_modules: List[str]
    learning_outcomes: List[str]
    cohort_start_dates: List[str]
    faqs: List[str]
    projects_use_cases: List[str]
    program_curriculum_coverage: str
    tools_frameworks_technologies: List[str]
    emi_or_financing_options: str


class StudentPersona(TypedDict):
    name: str
    gender: str
    archetype_id: str
    archetype_label: str
    age: int
    current_role: str
    city_tier: str
    backstory: str
    trigger_event: str
    hidden_secret: str
    misconception: str
    language_style: str
    common_vocabulary: List[str]
    financial_anxiety: int
    skepticism: int
    confusion_level: int
    ego_level: int
    # Legacy-compatible fields consumed by existing frontend/metrics.
    persona_type: str
    background: str
    career_stage: str
    financial_sensitivity: str
    risk_tolerance: str
    emotional_tone: str
    primary_objections: List[str]
    walk_away_likelihood: float
    expected_roi_months: int
    affordability_concern_level: int
    willingness_to_invest_score: int
    communication_style: str
    common_phrases: List[str]


class StudentInnerState(TypedDict):
    sentiment: str
    skepticism_level: int
    trust_score: int
    unresolved_concerns: List[str]


class AnalyzeUrlRequest(BaseModel):
    url: HttpUrl
    auth_token: str
    archetype_id: Optional[str] = None


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int


class AnalyzeUrlResponse(BaseModel):
    session_id: str
    program: Dict[str, Any]
    persona: StudentPersona
    source: str


class NegotiationConfig(BaseModel):
    session_id: str
    auth_token: str
    demo_mode: bool = True
    retry_mode: bool = False
    mode: str = "ai_vs_ai"
    archetype_id: Optional[str] = None


class ReportRequest(BaseModel):
    session_id: str
    auth_token: str
    transcript: List[Dict[str, Any]]
    analysis: Dict[str, Any]


class NegotiationState(TypedDict):
    round: int
    max_rounds: int
    messages: List[Dict[str, Any]]
    history_for_reporting: List[Dict[str, Any]]
    counsellor_position: Dict[str, Any]
    student_position: Dict[str, Any]
    student_inner_state: StudentInnerState
    program: ProgramSummary
    persona: StudentPersona
    deal_status: str
    negotiation_metrics: Dict[str, Any]
    retry_context: Dict[str, Any]


SESSION_STORE: Dict[str, Dict[str, Any]] = {}
AUTH_TOKENS: Dict[str, float] = {}
AUTH_FILE = Path(__file__).with_name("auth.json")
TRACE_OUTPUT_ROOT = Path(__file__).resolve().parent / "outputs" / "tracebility" / "runtime"
TRACE_PIPELINE_DIRS: Dict[str, str] = {
    "ai_vs_ai": "ai_vs_ai",
    "human_vs_ai": "human_vs_ai",
    "agent_powered_human_vs_ai": "agent_powered_human_vs_ai",
}
PDF_HINDI_FONT_NAME = "CloseWireHindi"
PDF_HINDI_FONT_BOLD_NAME = "CloseWireHindiBold"


def _pipeline_trace_dir(mode: str) -> Path:
    normalized = str(mode or "ai_vs_ai").strip().lower()
    folder = TRACE_PIPELINE_DIRS.get(normalized, "ai_vs_ai")
    return TRACE_OUTPUT_ROOT / folder


def _pipeline_debug_trace_file(mode: str) -> Path:
    return _pipeline_trace_dir(mode) / "negotiation_debug_trace.jsonl"


def _pipeline_traceability_file(mode: str) -> Path:
    return _pipeline_trace_dir(mode) / "conversation_traceability.json"


def _is_rag_pipeline_enabled() -> bool:
    raw = str(os.getenv("RAG_PIPELINE_ENABLED", "false")).strip().lower()
    # Accept common typo "flase" as false to avoid accidental activation.
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "flase", "no", "off", ""}:
        return False
    return False


def _has_devanagari(value: str) -> bool:
    text = str(value or "")
    return any("\u0900" <= ch <= "\u097F" for ch in text)


def _configure_pdf_fonts() -> Tuple[str, str]:
    base_font = "Helvetica"
    bold_font = "Helvetica-Bold"
    candidate_paths = [
        Path(__file__).resolve().parent / "assets" / "fonts" / "NotoSansDevanagari-Regular.ttf",
        Path(__file__).resolve().parent / "assets" / "fonts" / "NotoSansDevanagari-Bold.ttf",
        Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf"),
        Path("C:/Windows/Fonts/Nirmala.ttf"),
        Path("C:/Windows/Fonts/mangal.ttf"),
    ]
    regular_path = None
    bold_path = None
    for candidate in candidate_paths:
        lowered = candidate.name.lower()
        if "bold" in lowered and bold_path is None and candidate.exists():
            bold_path = candidate
        if "bold" not in lowered and regular_path is None and candidate.exists():
            regular_path = candidate
    if not regular_path:
        return base_font, bold_font
    try:
        pdfmetrics.registerFont(TTFont(PDF_HINDI_FONT_NAME, str(regular_path)))
        if bold_path:
            pdfmetrics.registerFont(TTFont(PDF_HINDI_FONT_BOLD_NAME, str(bold_path)))
            return PDF_HINDI_FONT_NAME, PDF_HINDI_FONT_BOLD_NAME
        return PDF_HINDI_FONT_NAME, PDF_HINDI_FONT_NAME
    except Exception:
        logger.exception("Failed to register Hindi PDF font. Falling back to Helvetica.")
        return base_font, bold_font


async def _run_post_session_jobs_safe(session_id: str, mode: str, trace_payload: Dict[str, Any]) -> None:
    if not _is_rag_pipeline_enabled():
        _write_debug_trace(
            "post_session_jobs_skipped",
            {
                "mode": mode,
                "session_id": session_id,
                "reason": "RAG_PIPELINE_ENABLED is false",
            },
        )
        return
    try:
        try:
            from backend.rag.post_session_runner import run_post_session_jobs
        except ImportError:
            from rag.post_session_runner import run_post_session_jobs

        result = await run_post_session_jobs(session_id=session_id, mode=mode, trace_payload=trace_payload)
        _write_debug_trace(
            "post_session_jobs_complete",
            {
                "mode": mode,
                "session_id": session_id,
                "result": _to_plain_json(result),
            },
        )
    except Exception as exc:
        _write_debug_trace(
            "post_session_jobs_failed",
            {
                "mode": mode,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": _truncate_trace_text(exc),
            },
        )

class ClientStreamClosed(Exception):
    """Raised when the websocket client disconnects during streaming."""


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_password_hash() -> str:
    default_hash = _sha256_hex("agenticaimagic2026")
    if not AUTH_FILE.exists():
        AUTH_FILE.write_text(json.dumps({"password_sha256": default_hash}, indent=2), encoding="utf-8")
        return default_hash
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        loaded_hash = str(data.get("password_sha256", "")).strip()
        if loaded_hash:
            return loaded_hash
    except Exception:
        logger.exception("Failed to parse auth.json; falling back to default hash")
    return default_hash


PASSWORD_SHA256 = _load_password_hash()


def _issue_auth_token() -> str:
    token = uuid.uuid4().hex
    AUTH_TOKENS[token] = datetime.now().timestamp() + AUTH_TOKEN_TTL_SECONDS
    return token


def _truncate_trace_text(value: Any, limit: int = 240) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated {len(text) - limit} chars)"


def _collect_candidate_finish_reasons(response: Any) -> List[str]:
    reasons: List[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        reason = str(getattr(candidate, "finish_reason", "")).strip()
        if reason:
            reasons.append(reason)
    return reasons


def _collect_chunk_finish_reasons(chunk: Any) -> List[str]:
    reasons: List[str] = []
    for candidate in getattr(chunk, "candidates", []) or []:
        reason = str(getattr(candidate, "finish_reason", "")).strip()
        if reason:
            reasons.append(reason)
    return reasons


def _looks_truncated_message(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    terminal = (".", "!", "?", "\"", "'", ")", "]", "}", "```", "</message>")
    return not value.endswith(terminal)


def _write_debug_trace(event: str, payload: Dict[str, Any]) -> None:
    if not NEGOTIATION_DEBUG_TRACE:
        return
    mode = str(payload.get("mode", "ai_vs_ai")).strip().lower()
    target_file = _pipeline_debug_trace_file(mode)
    entry = {
        "ts": datetime.now().isoformat(),
        "event": event,
        **payload,
    }
    try:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with target_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_to_plain_json(entry), ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("Failed to write debug trace event=%s", event)


def _build_traceability_payload(session_id: str, state: NegotiationState, analysis: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now().isoformat(),
        "session_id": session_id,
        "deal_status": state.get("deal_status"),
        "round": state.get("round"),
        "max_rounds": state.get("max_rounds"),
        "persona": state.get("persona"),
        "program": {
            "program_name": state.get("program", {}).get("program_name"),
            "program_fee_inr": state.get("program", {}).get("program_fee_inr"),
        },
        "student_inner_state": state.get("student_inner_state"),
        "negotiation_metrics": state.get("negotiation_metrics"),
        "final_offers": {
            "counsellor": state.get("counsellor_position", {}).get("current_offer"),
            "student": state.get("student_position", {}).get("current_offer"),
        },
        "analysis": analysis,
        "transcript": state.get("messages", []),
        "history_for_reporting": state.get("history_for_reporting", []),
    }


def _emit_conversation_traceability(session_id: str, state: NegotiationState, analysis: Dict[str, Any]) -> None:
    trace_payload = _build_traceability_payload(session_id, state, analysis)
    mode = str(state.get("mode", "ai_vs_ai")).strip().lower()
    target_file = _pipeline_traceability_file(mode)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(json.dumps(trace_payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _validate_auth_token(token: str) -> bool:
    expiry = AUTH_TOKENS.get(token)
    now = datetime.now().timestamp()
    if not expiry:
        return False
    if now > expiry:
        AUTH_TOKENS.pop(token, None)
        return False
    return True


def _require_auth_token(token: str) -> None:
    if not token or not _validate_auth_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or expired auth token")


def _safe_json_loads(text: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    payload = (text or "").strip()
    if not payload:
        logger.warning("Empty model response; using fallback JSON")
        return fallback

    # Try direct parse first.
    try:
        return json.loads(payload)
    except Exception:
        pass

    # Try markdown fenced JSON blocks.
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", payload, flags=re.IGNORECASE)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass

    # Try extracting the first top-level object from mixed prose.
    start = payload.find("{")
    end = payload.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = payload[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    logger.warning("Model returned non-JSON content; using fallback JSON")
    return fallback


def _to_plain_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_plain_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain_json(v) for v in value]
    if hasattr(value, "_pb"):
        try:
            return _to_plain_json(MessageToDict(value._pb, preserving_proto_field_name=True))
        except Exception:
            pass
    if hasattr(value, "items"):
        try:
            return {str(k): _to_plain_json(v) for k, v in value.items()}
        except Exception:
            pass
    if hasattr(value, "__iter__"):
        try:
            return [_to_plain_json(v) for v in list(value)]
        except Exception:
            pass
    return str(value)


def _call_function_json(
    client: genai.Client,
    model_name: str,
    prompt: str,
    function_name: str,
    function_description: str,
    parameters_schema: Dict[str, Any],
    fallback: Dict[str, Any],
) -> Dict[str, Any]:
    declaration = types.FunctionDeclaration(
        name=function_name,
        description=function_description,
        parameters=parameters_schema,
    )
    tool = types.Tool(function_declarations=[declaration])
    config = types.GenerateContentConfig(
        tools=[tool],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY",
                allowed_function_names=[function_name],
            )
        ),
    )

    response = None
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
        calls = getattr(response, "function_calls", None) or []
        for call in calls:
            if getattr(call, "name", "") == function_name:
                args = dict(getattr(call, "args", {}) or {})
                if args:
                    return _to_plain_json(args)
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                call = getattr(part, "function_call", None)
                if call and getattr(call, "name", "") == function_name:
                    args = dict(getattr(call, "args", {}) or {})
                    if args:
                        return _to_plain_json(args)
    except Exception:
        logger.exception("Gemini function-calling failed for %s", function_name)

    text = ""
    if response is not None:
        try:
            for candidate in getattr(response, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                if not content:
                    continue
                for part in getattr(content, "parts", []) or []:
                    part_text = getattr(part, "text", None)
                    if part_text:
                        text += part_text
            if not text:
                logger.warning("No text/function call returned for %s; likely blocked. Using fallback.", function_name)
        except Exception:
            logger.warning("Unable to extract candidate text for %s; using fallback.", function_name)
    return _to_plain_json(_safe_json_loads(text, fallback))


def sanitize_text(text: str) -> str:
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_inr_amount(text: str) -> int:
    raw = (text or "").lower()
    
    # Check for Lakhs/L
    lakh_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:lakh|l\b)", raw)
    if lakh_matches:
        values = [int(float(v) * 100_000) for v in lakh_matches]
        return max(1000, max(values))

    currency_matches = re.findall(
        r"(?:\u20b9|inr|rs\.?)\s*([0-9][0-9,]{3,10})",
        raw,
        flags=re.IGNORECASE,
    )
    if currency_matches:
        values = [int(v.replace(",", "")) for v in currency_matches]
        return max(1000, max(values))

    generic_matches = re.findall(r"\b([0-9][0-9,]{3,10})\b", raw)
    if generic_matches:
        values = [int(v.replace(",", "")) for v in generic_matches]
        return max(1000, max(values))
    return 4500


def _extract_all_offer_candidates(text: str) -> List[int]:
    raw = (text or "").lower()
    candidates = []
    
    # 1. Handle Lakhs/L
    lakh_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:lakh|l\b)", raw)
    for m in lakh_matches:
        try:
            candidates.append(int(float(m) * 100_000))
        except ValueError:
            pass

    # 2. INR prefix
    inr_matches = re.findall(r"(?:\u20b9|inr|rs\.?)\s*([0-9][0-9,]{2,10})", raw)
    for m in inr_matches:
        try:
            candidates.append(int(m.replace(",", "")))
        except ValueError:
            pass

    # 3. Generic large numbers
    generic_matches = re.findall(r"\b([1-9][0-9,]{4,10})\b", raw)
    for m in generic_matches:
        try:
            val = int(m.replace(",", ""))
            if val > 5000:
                candidates.append(val)
        except ValueError:
            pass

    usd_matches = re.findall(r"\$([0-9][0-9,]{2,10})", raw)
    for m in usd_matches:
        try:
            candidates.append(int(m.replace(",", "")))
        except ValueError:
            pass

    return candidates


def _derive_financials(program: Dict[str, Any], persona: Dict[str, Any]) -> Dict[str, int]:
    listed_fee = extract_inr_amount(str(program.get("program_fee_inr", "")))
    willingness = int(max(0, min(100, int(persona.get("willingness_to_invest_score", 50)))))

    student_budget = int(listed_fee * (0.75 + (willingness / 200.0)))
    student_budget = max(1000, student_budget)

    counsellor_offer = max(int(listed_fee * 1.10), int(student_budget * 1.05))
    floor_offer = max(int(counsellor_offer * 0.72), int(listed_fee * 0.65), 1000)
    student_opening = max(int(student_budget * 0.80), 1000)

    return {
        "listed_fee": listed_fee,
        "student_budget": student_budget,
        "counsellor_offer": counsellor_offer,
        "floor_offer": floor_offer,
        "student_opening": student_opening,
    }


def extract_from_url(url: str) -> str:
    """
    Scrapes text from a URL. Uses Jina Reader as a primary method for better LLM formatting.
    """
    # Try Jina Reader first
    try:
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(jina_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200 and len(response.text.strip()) > 200:
            return sanitize_text(response.text)
    except Exception as exc:
        logger.warning("Jina Reader failed for %s: %s. Falling back to direct scraping.", url, str(exc))

    # Fallback to direct requests
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "svg", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        return sanitize_text(text)
    except Exception as exc:
        logger.error("Scraping fully failed for %s: %s", url, str(exc))
        return f"Error extracting from URL: {str(exc)}"


def _extract_labeled_block(raw: str, label: str, stop_labels: List[str]) -> str:
    stop_pattern = "|".join(re.escape(item) for item in stop_labels)
    pattern = rf"{re.escape(label)}:\s*(.*?)(?:\n(?:{stop_pattern})\s*:|$)"
    match = re.search(pattern, raw, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_tag_block(raw: str, tag: str) -> str:
    closed = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", raw, flags=re.IGNORECASE | re.DOTALL)
    if closed:
        return closed.group(1).strip()
    # Fallback when model forgets closing tag.
    open_only = re.search(rf"<{tag}>\s*(.*)$", raw, flags=re.IGNORECASE | re.DOTALL)
    if open_only:
        return open_only.group(1).strip()
    return ""


def _extract_message_block(raw: str) -> str:
    # Handles both multi-line and single-line labeled output where control labels may be inline.
    pattern = (
        r"MESSAGE:\s*(.*?)(?:(?:\n|\r|\s)"
        r"(?:INTERNAL_THOUGHT|UPDATED_STATS|UPDATED_STATE|EMOTIONAL_STATE|STRATEGIC_INTENT|TECHNIQUES_USED|CONFIDENCE_SCORE)\s*:|$)"
    )
    match = re.search(pattern, raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    message = match.group(1).strip()
    message = re.sub(
        r"(?:INTERNAL_THOUGHT|UPDATED_STATS|UPDATED_STATE|EMOTIONAL_STATE|STRATEGIC_INTENT|TECHNIQUES_USED|CONFIDENCE_SCORE)\s*:.*$",
        "",
        message,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    return message


def _extract_first_json_object(raw: str) -> Dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _extract_unlabeled_message(raw: str) -> str:
    lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
    if not lines:
        return ""
    label_prefixes = (
        "INTERNAL_THOUGHT:",
        "UPDATED_STATS:",
        "UPDATED_STATE:",
        "MESSAGE:",
        "EMOTIONAL_STATE:",
        "STRATEGIC_INTENT:",
        "TECHNIQUES_USED:",
        "CONFIDENCE_SCORE:",
    )
    cleaned = [line for line in lines if not line.upper().startswith(label_prefixes)]
    return " ".join(cleaned).strip()


def _clamp_score(value: Any, fallback: int = 50) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = fallback
    return max(0, min(100, parsed))


def _merge_student_inner_state(current: StudentInnerState, updates: Dict[str, Any]) -> StudentInnerState:
    merged: StudentInnerState = {
        "sentiment": str(current.get("sentiment", "curious")),
        "skepticism_level": _clamp_score(current.get("skepticism_level", 50)),
        "trust_score": _clamp_score(current.get("trust_score", 50)),
        "unresolved_concerns": [str(item) for item in (current.get("unresolved_concerns") or [])],
    }
    if not updates:
        return merged
    merged["skepticism_level"] = _clamp_score(
        updates.get("skepticism_level", updates.get("resistance", merged["skepticism_level"])),
        merged["skepticism_level"],
    )
    merged["trust_score"] = _clamp_score(
        updates.get("trust_score", updates.get("trust", merged["trust_score"])),
        merged["trust_score"],
    )
    if updates.get("sentiment"):
        merged["sentiment"] = str(updates.get("sentiment")).strip().lower()
    if isinstance(updates.get("unresolved_concerns"), list):
        merged["unresolved_concerns"] = [str(item).strip() for item in updates["unresolved_concerns"] if str(item).strip()]
    return merged


def _extract_chunk_text(chunk: Any) -> str:
    text = getattr(chunk, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    fragments: List[str] = []
    for candidate in getattr(chunk, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                fragments.append(part_text)
    return "".join(fragments)


def _extract_response_text_from_non_stream(response: Any) -> str:
    parts: List[str] = []
    direct_text = getattr(response, "text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        parts.append(direct_text)
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(part_text)
    return "".join(parts).strip()


def _extract_response_fields(text: str) -> Dict[str, Any]:
    raw = text or ""
    techniques: List[str] = []
    message = _extract_tag_block(raw, "message") or _extract_message_block(raw)
    thought = _extract_tag_block(raw, "thought") or _extract_labeled_block(
        raw,
        "INTERNAL_THOUGHT",
        ["UPDATED_STATS", "UPDATED_STATE", "MESSAGE", "STRATEGIC_INTENT", "EMOTIONAL_STATE"],
    )
    intent = _extract_tag_block(raw, "intent") or _extract_labeled_block(
        raw,
        "STRATEGIC_INTENT",
        ["MESSAGE", "EMOTIONAL_STATE", "CONFIDENCE_SCORE"],
    )
    emotional_state = (
        _extract_tag_block(raw, "emotional_state")
        or _extract_tag_block(raw, "emotion")
        or "calm"
    )
    confidence = 60

    updated_stats_raw = _extract_tag_block(raw, "stats")
    if not updated_stats_raw:
        updated_stats_raw = _extract_labeled_block(
            raw,
            "UPDATED_STATS",
            ["MESSAGE", "STRATEGIC_INTENT", "EMOTIONAL_STATE", "INTERNAL_THOUGHT", "UPDATED_STATE"],
        )
    if not updated_stats_raw:
        updated_stats_raw = _extract_labeled_block(
            raw,
            "UPDATED_STATE",
            ["MESSAGE", "STRATEGIC_INTENT", "EMOTIONAL_STATE", "INTERNAL_THOUGHT", "UPDATED_STATS"],
        )
    updated_stats = _extract_first_json_object(updated_stats_raw)

    techniques_raw = _extract_tag_block(raw, "techniques")
    if techniques_raw:
        parsed_techniques = _extract_first_json_object(f"{{\"items\": {techniques_raw}}}").get("items", [])
        if isinstance(parsed_techniques, list):
            techniques = [str(item).strip() for item in parsed_techniques if str(item).strip()]
        elif not techniques:
            techniques = [item.strip() for item in techniques_raw.split(",") if item.strip()]
    if not techniques:
        techniques_match = re.search(r"TECHNIQUES_USED:\s*\[(.*?)\]", raw, flags=re.IGNORECASE | re.DOTALL)
        if techniques_match:
            techniques = [
                item.strip().strip('"').strip("'")
                for item in techniques_match.group(1).split(",")
                if item.strip()
            ]

    confidence_raw = _extract_tag_block(raw, "confidence") or _extract_tag_block(raw, "confidence_score")
    if confidence_raw:
        confidence = _clamp_score(confidence_raw, 60)
    else:
        confidence_match = re.search(r"CONFIDENCE_SCORE:\s*([0-9]+(?:\.[0-9]+)?)", raw, flags=re.IGNORECASE)
        if confidence_match:
            try:
                confidence = int(float(confidence_match.group(1)))
            except Exception:
                confidence = 60

    if emotional_state == "calm":
        emotional_match = re.search(r"EMOTIONAL_STATE:\s*([a-zA-Z_ -]+)", raw, flags=re.IGNORECASE)
        if emotional_match:
            emotional_state = emotional_match.group(1).strip().lower()

    if not message:
        clean_text = re.sub(r"<thought>.*?</thought>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<stats>.*?</stats>", " ", clean_text, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<intent>.*?</intent>", " ", clean_text, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<emotional_state>.*?</emotional_state>", " ", clean_text, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<emotion>.*?</emotion>", " ", clean_text, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<techniques>.*?</techniques>", " ", clean_text, flags=re.IGNORECASE | re.DOTALL)
        clean_text = re.sub(r"<confidence(?:_score)?>.*?</confidence(?:_score)?>", " ", clean_text, flags=re.IGNORECASE | re.DOTALL)
        clean_text = clean_text.replace("<message>", " ").replace("</message>", " ")
        message = _extract_unlabeled_message(clean_text)
    if not message:
        message = "..."

    message = re.sub(r"\s+\n", "\n", message).strip()
    return {
        "message": message,
        "techniques": techniques,
        "intent": intent,
        "confidence_score": max(0, min(100, confidence)),
        "emotional_state": emotional_state,
        "internal_thought": thought,
        "updated_stats": updated_stats,
    }


def _extract_counsellor_message(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "..."
    tagged = _extract_tag_block(raw, "message")
    if tagged:
        return re.sub(r"\s+\n", "\n", tagged).strip() or "..."
    return re.sub(r"\s+\n", "\n", raw).strip() or "..."


def _trim_messages(messages: List[Dict[str, Any]], max_messages: int = 12) -> List[Dict[str, Any]]:
    return messages[-max_messages:]


def _compact_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _looks_like_student_role_drift(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lowered = text.lower()
    hard_patterns = (
        r"\bas your counsellor\b",
        r"\bi need to explain\b",
        r"\blet me explain\b",
        r"\bi can help you\b",
        r"\bi will help you\b",
        r"\bour (program|course|curriculum|placement team)\b",
        r"\bwe (offer|provide|have|guarantee)\b",
    )
    for pattern in hard_patterns:
        if re.search(pattern, lowered):
            return True
    advisory_markers = (
        "you should",
        "i recommend",
        "i suggest",
        "please enroll",
        "you can enroll",
        "we can assist you with placement",
    )
    has_advisory = any(marker in lowered for marker in advisory_markers)
    has_question = "?" in text
    if has_advisory and not has_question:
        return True
    return False


def _student_program_snapshot(program: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "program_name": program.get("program_name", ""),
        "value_proposition": program.get("value_proposition", ""),
        "duration": program.get("duration", ""),
        "format": program.get("format", ""),
        "weekly_time_commitment": program.get("weekly_time_commitment", ""),
        "program_fee_inr": program.get("program_fee_inr", ""),
        "placement_support_details": program.get("placement_support_details", ""),
        "certification_details": program.get("certification_details", ""),
        "curriculum_modules": list(program.get("curriculum_modules", [])[:8]),
        "emi_or_financing_options": program.get("emi_or_financing_options", ""),
    }


def _build_retry_context_prompt(state: NegotiationState) -> str:
    transcript = "\n".join(
        f"{m['agent'].upper()}: {m['content']}" for m in _trim_messages(state.get("messages", []), 6)
    )
    return (
        "RETRY_CONTEXT:\n"
        f"PROGRAM_SNAPSHOT:\n{json.dumps(_student_program_snapshot(state.get('program', {})), ensure_ascii=False)}\n"
        f"TRANSCRIPT_CONTEXT:\n{transcript}"
    )


def _pick_live_mode_archetype() -> str:
    return random.choice(["desperate_switcher", "skeptical_shopper"])


def _resolve_selected_archetype(archetype_id: Optional[str]) -> Optional[str]:
    raw = str(archetype_id or "").strip().lower()
    if not raw:
        return None
    if raw == "random":
        return random.choice(list(ARCHETYPE_CONFIGS.keys()))
    if raw in ARCHETYPE_CONFIGS:
        return raw
    return None


async def _generate_coaching_tips(
    client: genai.Client,
    model_name: str,
    state: NegotiationState,
    last_student_msg: Dict[str, Any],
) -> Dict[str, Any]:
    mode = str(state.get("mode", "ai_vs_ai")).strip().lower()
    round_number = int(state.get("round", 1))
    archetype_id = str(state.get("persona", {}).get("archetype_id", "")).strip().lower()
    is_hindi = archetype_id == "skeptical_shopper"
    fallback = (
        {
            "analysis": "मुख्य चिंता अभी भी अनसुलझी है।",
            "suggestions": [
                {"title": "चिंता को मान्यता दें", "description": "मैं आपकी चिंता समझता हूँ, यह एक वैध प्रश्न है।"},
                {"title": "बाधा पूछें", "description": "क्या आपको समय या बजट को लेकर कोई विशेष परेशानी है?"},
                {"title": "समापन प्रश्न पूछें", "description": "अगर हम इस मुद्दे को हल कर दें, तो क्या आप आज नामांकन के लिए तैयार हैं?"},
            ],
            "fact_check": "आपत्ति से जुड़ा एक ठोस कार्यक्रम तथ्य बताएं।",
        }
        if is_hindi
        else {
            "analysis": "Primary concern is still unresolved.",
            "suggestions": [
                {"title": "Acknowledge Concern", "description": "I hear your hesitation, and it is important we address this."},
                {"title": "Probe Constraint", "description": "Is there a specific constraint stopping you right now?"},
                {"title": "Closing Question", "description": "If we resolve this, would you be ready to proceed?"},
            ],
            "fact_check": "Use one concrete programme fact relevant to the objection.",
        }
    )
    transcript_tail = _trim_messages(state.get("messages", []), 8)
    program_snapshot = _student_program_snapshot(state.get("program", {}))
    last_student_text = str(last_student_msg.get("content", "")).strip()
    prompt = f"""
ROLE: Real-time Negotiation Coach.
You are whispering to a junior counsellor in a live call.
Be short, direct, and actionable.

CONTEXT:
- Pipeline mode: {mode}
- Round: {round_number}
- Prospect archetype: {state.get("persona", {}).get("archetype_label", "Prospect")}
- Program: {state.get("program", {}).get("program_name", "Program")}

PROGRAM FACTS:
{json.dumps(program_snapshot, ensure_ascii=False)}

TRANSCRIPT TAIL:
{json.dumps(transcript_tail, ensure_ascii=False)}

LAST STUDENT MESSAGE:
{last_student_text}

TASK:
1. Decode subtext in one line.
2. Provide exactly 3 suggestions for counsellor speech.
   - For each suggestion provide:
     - title: < 4 words, imperative label (e.g. "Ask Budget").
     - description: The actual suggested dialogue or detailed instruction (e.g. "Could you share your approximate budget range?").
3. Provide one fact_check line tied to the objection.
4. Language:
   - If prospect archetype is skeptical_shopper, return only Hindi (Devanagari).
   - Otherwise return English.

OUTPUT JSON:
{{
  "analysis": "<one-line subtext>",
  "suggestions": [
    {{"title": "<short label>", "description": "<detailed text>"}},
    {{"title": "<short label>", "description": "<detailed text>"}},
    {{"title": "<short label>", "description": "<detailed text>"}}
  ],
  "fact_check": "<single concrete fact>"
}}
"""
    _write_debug_trace(
        "copilot_generate_start",
        {
            "mode": mode,
            "round": round_number,
            "student_head": _truncate_trace_text(last_student_text, 160),
        },
    )
    parsed = await asyncio.to_thread(
        _call_function_json,
        client,
        model_name,
        prompt,
        "set_copilot_coaching_tips",
        "Return concise coaching analysis, three structured suggestions, and one fact check.",
        {
            "type": "object",
            "properties": {
                "analysis": {"type": "string"},
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["title", "description"],
                    },
                    "minItems": 3,
                    "maxItems": 3,
                },
                "fact_check": {"type": "string"},
            },
            "required": ["analysis", "suggestions", "fact_check"],
        },
        fallback,
    )
    parsed = _to_plain_json(parsed)
    
    # Validation / Normalization
    raw_suggestions = parsed.get("suggestions")
    normalized_suggestions = []
    if isinstance(raw_suggestions, list):
        for item in raw_suggestions:
            if isinstance(item, dict) and item.get("title") and item.get("description"):
                normalized_suggestions.append({
                    "title": str(item["title"]).strip(), 
                    "description": str(item["description"]).strip()
                })
            elif isinstance(item, str):
                # Legacy string fallback
                normalized_suggestions.append({
                    "title": "Suggestion",
                    "description": str(item).strip()
                })
                
    if not normalized_suggestions:
        normalized_suggestions = list(fallback["suggestions"])
        
    normalized_suggestions = normalized_suggestions[:3]
    while len(normalized_suggestions) < 3:
        normalized_suggestions.append(fallback["suggestions"][len(normalized_suggestions)])
        
    normalized = {
        "analysis": str(parsed.get("analysis") or fallback["analysis"]).strip(),
        "suggestions": normalized_suggestions,
        "fact_check": str(parsed.get("fact_check") or fallback["fact_check"]).strip(),
    }
    _write_debug_trace(
        "copilot_generate_complete",
        {
            "mode": mode,
            "round": round_number,
            "analysis_head": _truncate_trace_text(normalized["analysis"], 140),
            "suggestion_count": len(normalized["suggestions"]),
            "fact_head": _truncate_trace_text(normalized["fact_check"], 140),
        },
    )
    return normalized


async def _classify_human_input(
    client: genai.Client,
    model_name: str,
    text: str,
    state: NegotiationState,
    round_number: int,
    message_id: str,
) -> Dict[str, Any]:
    clean_text = str(text or "").strip()
    if not clean_text:
        clean_text = "..."
    _write_debug_trace(
        "human_shadow_classify_start",
        {
            "mode": "human_vs_ai",
            "round": round_number,
            "message_id": message_id,
            "text_head": _truncate_trace_text(clean_text, 180),
        },
    )

    fallback = {
        "techniques": [],
        "strategic_intent": "Human counsellor message",
        "confidence_score": 60,
        "emotional_state": "calm",
    }
    prompt = f"""
Analyze this counsellor statement and return structured metadata only.

STATEMENT:
{clean_text}

ROUND:
{round_number}

CONTEXT:
{json.dumps(_trim_messages(state.get("messages", []), 6), ensure_ascii=False)}
"""
    parsed = await asyncio.to_thread(
        _call_function_json,
        client,
        model_name,
        prompt,
        "set_human_shadow_observer",
        "Extract techniques, strategic intent, confidence score, and emotional state for a human counsellor turn.",
        {
            "type": "object",
            "properties": {
                "techniques": {"type": "array", "items": {"type": "string"}},
                "strategic_intent": {"type": "string"},
                "confidence_score": {"type": "number"},
                "emotional_state": {"type": "string"},
            },
            "required": ["techniques", "strategic_intent", "confidence_score", "emotional_state"],
        },
        fallback,
    )
    parsed = _to_plain_json(parsed)
    techniques = [str(item).strip() for item in (parsed.get("techniques") or []) if str(item).strip()][:8]
    strategic_intent = str(parsed.get("strategic_intent") or fallback["strategic_intent"]).strip()
    confidence_score = _clamp_score(parsed.get("confidence_score"), fallback["confidence_score"])
    emotional_state = str(parsed.get("emotional_state") or fallback["emotional_state"]).strip().lower() or "calm"
    _write_debug_trace(
        "human_shadow_classify_complete",
        {
            "mode": "human_vs_ai",
            "round": round_number,
            "message_id": message_id,
            "technique_count": len(techniques),
            "intent_head": _truncate_trace_text(strategic_intent, 140),
            "confidence_score": confidence_score,
            "emotional_state": emotional_state,
        },
    )

    return {
        "id": message_id,
        "round": round_number,
        "agent": "counsellor",
        "content": clean_text,
        "techniques": techniques,
        "strategic_intent": strategic_intent,
        "confidence_score": confidence_score,
        "emotional_state": emotional_state,
        "internal_thought": "",
        "updated_stats": {},
        "updated_state": {},
        "timestamp": datetime.now().isoformat(),
        "generation_mode": "human_shadow",
    }


def _analyze_program(url: str, archetype_id: Optional[str] = None) -> Tuple[ProgramSummary, str]:
    client, negotiation_model_name, _ = get_client_and_models()
    source = "url_content"
    clean_text = extract_from_url(url)[:25000]
    
    is_product = str(archetype_id).strip().lower() in ["car_buyer", "discount_hunter"]
    
    if clean_text.startswith("Error extracting from URL:") or len(clean_text) < 300:
        source = "fallback"
        
    fallback = {
        "program_name": "Unknown Product" if is_product else "Unknown Program",
        "value_proposition": "High-quality product value." if is_product else "Career outcomes through practical learning.",
        "key_features": ["Reliability", "Performance"] if is_product else ["Structured curriculum", "Industry relevance"],
        "target_audience": "General consumers" if is_product else "Early and mid-career professionals",
        "positioning_angle": "Value-driven purchase" if is_product else "Outcome-focused upskilling",
        "duration": "N/A",
        "format": "N/A",
        "weekly_time_commitment": "N/A",
        "program_fee_inr": "Price on Request",
        "placement_support_details": "N/A",
        "certification_details": "N/A",
        "curriculum_modules": [],
        "learning_outcomes": [],
        "cohort_start_dates": [],
        "faqs": [],
        "projects_use_cases": [],
        "program_curriculum_coverage": "N/A",
        "tools_frameworks_technologies": [],
        "emi_or_financing_options": "Available",
    }
    
    product_type_hint = "PRODUCT (e.g., Car, Gadget)" if is_product else "PROGRAM (e.g., Course, Bootcamp)"
    
    prompt = f"""
Analyze content of this URL for an expert specialist. Extract concrete facts only.
If the content is missing or unreachable, return the fallback values provided in the tool schema.
DO NOT hallucinate product names or features if they are not explicitly mentioned in the text.
If you don't know the name, use "Unknown {product_type_hint}".

URL: {url}
PAGE_TEXT:
{clean_text}
"""
    parsed = _call_function_json(
        client=client,
        model_name=negotiation_model_name,
        prompt=prompt,
        function_name="set_program_summary",
        function_description=f"Return structured details extracted from URL content for a {product_type_hint}.",
        parameters_schema={
            "type": "object",
            "properties": {
                "program_name": {"type": "string", "description": "The specific name of the car/gadget/course."},
                "value_proposition": {"type": "string"},
                "key_features": {"type": "array", "items": {"type": "string"}},
                "target_audience": {"type": "string"},
                "positioning_angle": {"type": "string"},
                "duration": {"type": "string"},
                "format": {"type": "string"},
                "weekly_time_commitment": {"type": "string"},
                "program_fee_inr": {"type": "string"},
                "placement_support_details": {"type": "string"},
                "certification_details": {"type": "string"},
                "curriculum_modules": {"type": "array", "items": {"type": "string"}},
                "learning_outcomes": {"type": "array", "items": {"type": "string"}},
                "cohort_start_dates": {"type": "array", "items": {"type": "string"}},
                "faqs": {"type": "array", "items": {"type": "string"}},
                "projects_use_cases": {"type": "array", "items": {"type": "string"}},
                "program_curriculum_coverage": {"type": "string"},
                "tools_frameworks_technologies": {"type": "array", "items": {"type": "string"}},
                "emi_or_financing_options": {"type": "string"},
            },
            "required": [
                "program_name",
                "value_proposition",
                "key_features",
                "target_audience",
                "positioning_angle",
                "duration",
                "format",
                "weekly_time_commitment",
                "program_fee_inr",
                "placement_support_details",
                "certification_details",
                "curriculum_modules",
                "learning_outcomes",
                "cohort_start_dates",
                "faqs",
                "projects_use_cases",
                "program_curriculum_coverage",
                "tools_frameworks_technologies",
                "emi_or_financing_options",
            ],
        },
        fallback=fallback,
    )
    return _to_plain_json(parsed), source


def _generate_persona(program: ProgramSummary, forced_archetype_id: Optional[str] = None) -> StudentPersona:
    client, negotiation_model_name, _ = get_client_and_models()
    if forced_archetype_id and forced_archetype_id in ARCHETYPE_CONFIGS:
        archetype_id = forced_archetype_id
    else:
        archetype_id = random.choice(list(ARCHETYPE_CONFIGS.keys()))
    archetype = ARCHETYPE_CONFIGS.get(archetype_id, ARCHETYPE_CONFIGS["desperate_switcher"])
    selected_name, selected_gender = _pick_persona_identity(archetype_id)
    language_style = "Hindi" if archetype_id == "skeptical_shopper" else random.choice(
        ["Indian Academic English", "Corporate Indian English", "Formal Indian English", "Passive Indian English"]
    )
    is_product = archetype_id in ["car_buyer", "discount_hunter"]
    subject_type = "Consumer/Product Buyer" if is_product else "Learner/Student"
    
    prompt = f"""
Generate a realistic Indian {subject_type} persona and call the function.
You MUST keep archetype_id exactly as: {archetype_id}
Archetype label: {ARCHETYPE_LABELS.get(archetype_id, archetype_id)}
Core drive: {archetype['core_drive']}
Stress trigger: {archetype['stress_trigger']}
Emotional response: {archetype['emotional_response']}
Language instruction: {archetype['language_instruction']}

Use realistic Indian context.
Do NOT invent identity beyond the parameters.
Use exactly this name: "{selected_name}"
Use exactly this gender: "{selected_gender}".
If archetype_id is skeptical_shopper, force language_style as pure Hindi (Devanagari). No Hinglish.
No profanity.

{subject_type.upper()} CONTEXT:
{"Evaluate a high-value purchase (Car/Gadget). Focus on ownership value, specifications, and family needs." if is_product else "Evaluate an educational path. Focus on career growth, skills, and placements."}

PROGRAM/PRODUCT:
{json.dumps(program)}
"""
    fallback_name, fallback_gender = selected_name, selected_gender
    fallback: StudentPersona = {
        "name": fallback_name,
        "gender": fallback_gender,
        "archetype_id": archetype_id,
        "archetype_label": ARCHETYPE_LABELS.get(archetype_id, archetype_id),
        "age": random.randint(25, 45) if is_product else random.randint(21, 34),
        "current_role": random.choice(["Business Owner", "Senior Lead", "Software Engineer", "Consultant"]) if is_product else random.choice(["BPO Employee", "Final Year B.Tech Student", "Manual Tester", "Support Engineer", "Job Seeker"]),
        "city_tier": random.choice(["Tier-1", "Tier-2"]),
        "backstory": "Needs a reliable vehicle for family and daily commute." if is_product else "Family expectations are rising and career progress feels stuck.",
        "trigger_event": "Expanding family needs or upgrading for better status." if is_product else "Saw a friend get a better package after upskilling.",
        "hidden_secret": "Checking multiple dealerships for the best exchange bonus." if is_product else "Scared of wasting money and failing to complete what is started.",
        "misconception": "Highest price always means highest reliability." if is_product else "Certificate alone guarantees shortlisting and placement.",
        "language_style": language_style,
        "common_vocabulary": ["Mileage", "On-road", "Warranty", "Service", "Discount", "Exchange"] if is_product else ["Package", "Placement", "Fresher", "Backlog", "Refund", "Scope"],
        "financial_anxiety": random.randint(30, 80),
        "skepticism": random.randint(40, 95),
        "confusion_level": random.randint(20, 70),
        "ego_level": random.randint(30, 90),
        # Legacy compatibility
        "persona_type": archetype_id,
        "background": "Evaluating a high-value purchase." if is_product else "Prospective learner evaluating an AI upskilling path.",
        "career_stage": random.choice(["mid", "senior"]) if is_product else random.choice(["early", "mid"]),
        "financial_sensitivity": random.choice(["medium", "high"]),
        "risk_tolerance": random.choice(["low", "medium"]),
        "emotional_tone": random.choice(["skeptical", "negotiating", "anxious"]),
        "primary_objections": ["On-road price", "Maintenance costs", "Resale value", "Tech features"] if is_product else ["Placement credibility", "Fee value", "Difficulty for freshers", "Time commitment"],
        "walk_away_likelihood": round(random.uniform(0.2, 0.6), 2),
        "expected_roi_months": random.randint(24, 60) if is_product else random.randint(4, 18),
        "affordability_concern_level": random.randint(30, 85),
        "willingness_to_invest_score": random.randint(40, 80),
        "communication_style": random.choice(["direct", "aggressive", "skeptical", "demanding"]),
        "common_phrases": ["Best final price kya hai?", "Exchange bonus kitna milega?", "Maintenance cost ka scene kya hai?"] if is_product else ["Placement ka scene kya hai?", "Is this really worth it?", "Mera paisa waste toh nahi hoga?"],
    }
    if archetype_id == "skeptical_shopper":
        fallback["common_vocabulary"] = ["फीस", "प्लेसमेंट", "भरोसा", "करियर", "नौकरी", "परिणाम"]
        fallback["common_phrases"] = [
            "फीस इतनी ज़्यादा क्यों है?",
            "प्लेसमेंट का भरोसा कैसे होगा?",
            "इसका करियर पर असली असर क्या है?",
        ]
    parsed = _call_function_json(
        client=client,
        model_name=negotiation_model_name,
        prompt=prompt,
        function_name="set_persona",
        function_description=f"Return a structured Indian {subject_type} persona with narrative depth and hidden blockers.",
        parameters_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "gender": {"type": "string", "enum": ["male", "female"]},
                "archetype_id": {"type": "string", "enum": list(ARCHETYPE_LABELS.keys())},
                "archetype_label": {"type": "string"},
                "age": {"type": "integer"},
                "current_role": {"type": "string"},
                "city_tier": {"type": "string", "enum": ["Tier-1", "Tier-2"]},
                "backstory": {"type": "string"},
                "trigger_event": {"type": "string"},
                "hidden_secret": {"type": "string"},
                "misconception": {"type": "string"},
                "language_style": {"type": "string"},
                "common_vocabulary": {"type": "array", "items": {"type": "string"}},
                "financial_anxiety": {"type": "integer"},
                "skepticism": {"type": "integer"},
                "confusion_level": {"type": "integer"},
                "ego_level": {"type": "integer"},
            },
            "required": [
                "name",
                "gender",
                "archetype_id",
                "archetype_label",
                "age",
                "current_role",
                "city_tier",
                "backstory",
                "trigger_event",
                "hidden_secret",
                "misconception",
                "language_style",
                "common_vocabulary",
                "financial_anxiety",
                "skepticism",
                "confusion_level",
                "ego_level",
            ],
        },
        fallback=fallback,
    )
    parsed = _to_plain_json(parsed)
    parsed["name"] = str(parsed.get("name") or fallback["name"]).strip() or fallback["name"]
    parsed["gender"] = str(parsed.get("gender") or fallback["gender"]).strip().lower()
    if parsed["gender"] not in {"male", "female"}:
        parsed["gender"] = fallback["gender"]
    parsed["name"] = fallback_name
    parsed["gender"] = fallback_gender
    parsed["archetype_id"] = str(parsed.get("archetype_id") or archetype_id)
    if parsed["archetype_id"] not in ARCHETYPE_LABELS:
        parsed["archetype_id"] = archetype_id
    parsed["archetype_label"] = str(
        parsed.get("archetype_label") or ARCHETYPE_LABELS.get(parsed["archetype_id"], parsed["archetype_id"])
    )
    parsed["age"] = int(max(18, min(50, int(parsed.get("age", fallback["age"])))))
    parsed["current_role"] = str(parsed.get("current_role") or fallback["current_role"])
    parsed["city_tier"] = "Tier-1" if str(parsed.get("city_tier")).strip() == "Tier-1" else "Tier-2"
    parsed["language_style"] = (
        "Hindi" if parsed["archetype_id"] == "skeptical_shopper" else str(parsed.get("language_style") or fallback["language_style"])
    )
    parsed["common_vocabulary"] = [str(item) for item in (parsed.get("common_vocabulary") or fallback["common_vocabulary"])][:8]
    parsed["financial_anxiety"] = _clamp_score(parsed.get("financial_anxiety", fallback["financial_anxiety"]))
    parsed["skepticism"] = _clamp_score(parsed.get("skepticism", fallback["skepticism"]))
    parsed["confusion_level"] = _clamp_score(parsed.get("confusion_level", fallback["confusion_level"]))
    parsed["ego_level"] = _clamp_score(parsed.get("ego_level", fallback["ego_level"]))
    # Legacy-compatible fields expected by current UI and pricing logic.
    parsed["persona_type"] = str(parsed.get("persona_type") or parsed["archetype_id"])
    parsed["background"] = str(parsed.get("background") or fallback["background"])
    parsed["career_stage"] = str(parsed.get("career_stage") or fallback["career_stage"])
    parsed["financial_sensitivity"] = str(parsed.get("financial_sensitivity") or fallback["financial_sensitivity"])
    parsed["risk_tolerance"] = str(parsed.get("risk_tolerance") or fallback["risk_tolerance"])
    parsed["emotional_tone"] = str(parsed.get("emotional_tone") or fallback["emotional_tone"])
    parsed["primary_objections"] = [str(item) for item in (parsed.get("primary_objections") or fallback["primary_objections"])][:6]
    parsed["walk_away_likelihood"] = float(max(0.0, min(1.0, float(parsed.get("walk_away_likelihood", fallback["walk_away_likelihood"])))))
    parsed["expected_roi_months"] = int(max(1, min(60, int(parsed.get("expected_roi_months", fallback["expected_roi_months"])))))
    parsed["affordability_concern_level"] = int(max(0, min(100, int(parsed.get("affordability_concern_level", fallback["affordability_concern_level"])))))
    parsed["willingness_to_invest_score"] = int(max(0, min(100, int(parsed.get("willingness_to_invest_score", fallback["willingness_to_invest_score"])))))
    parsed["communication_style"] = str(parsed.get("communication_style") or fallback["communication_style"])
    parsed["common_phrases"] = [str(item) for item in (parsed.get("common_phrases") or fallback["common_phrases"])][:6]
    return parsed


def _is_valid_student_persona_schema(persona: Dict[str, Any]) -> bool:
    required = {
        "gender",
        "archetype_id",
        "archetype_label",
        "age",
        "current_role",
        "city_tier",
        "backstory",
        "trigger_event",
        "hidden_secret",
        "misconception",
        "language_style",
        "common_vocabulary",
        "financial_anxiety",
        "skepticism",
        "confusion_level",
        "ego_level",
    }
    return required.issubset(set(persona.keys()))


def _build_counsellor_prompt(state: NegotiationState) -> str:
    transcript = "\n".join(
        f"{m['agent'].upper()}: {m['content']}" for m in _trim_messages(state["messages"], 12)
    )
    retry_context = state.get("retry_context", {})
    retry_note = ""
    if retry_context.get("is_retry"):
        mistakes = retry_context.get("mistakes", [])
        unresolved = retry_context.get("primary_unresolved_objection", "Not specified")
        retry_note = f"""
PREVIOUS ATTEMPT FAILED.
Failure Reasons:
- {", ".join(mistakes) if mistakes else "Not available"}
- Unresolved Objection: {unresolved}
In this run:
- Correct previous mistakes.
- Resolve the main objection earlier.
- Improve emotional calibration.
"""
    persona = state.get("persona", {})
    archetype_id = str(persona.get("archetype_id", "")).strip().lower()
    if archetype_id == "skeptical_shopper":
        counsellor_language_rules = (
            "LANGUAGE REQUIREMENT:\n"
            "- Speak only in natural Hindi (Devanagari script).\n"
            "- No Hinglish, no English code-mixing.\n"
            "- This rule applies from the very first counsellor turn."
        )
    else:
        counsellor_language_rules = (
            "LANGUAGE REQUIREMENT:\n"
            "- Use clear, professional English matching the active simulation style."
        )
        
    role_title = "Senior Admissions Counsellor"
    objective_term = "enrollment"
    product_label = "PROGRAM"
    do_not_rules = (
        "- Promise guaranteed jobs\n"
        "- Overstate placement outcomes\n"
        "- Invent program details"
    )
    customer_term = "student"
    intent_examples = "fee, placement, eligibility, curriculum, duration, financing, outcomes, comparison, trust-risk"
    nudge_examples = (
        "  - \"Would you like a quick view of the capstone outcomes?\"\n"
        "  - \"Should I break down placement eligibility in 30 seconds?\"\n"
        "  - \"Do you want a fee + EMI snapshot for your case?\""
    )
    
    if archetype_id in ["car_buyer", "discount_hunter"]:
        role_title = "Expert Product Specialist / Sales Executive"
        objective_term = "purchase"
        product_label = "PRODUCT"
        do_not_rules = (
            "- Promise unrealistic discounts\n"
            "- Overstate product features or warranty\n"
            "- Invent product specifications"
        )
        customer_term = "customer"
        intent_examples = "price, features, warranty, specifications, financing, delivery, comparison, trust-risk"
        nudge_examples = (
          "  - \"Would you like a quick breakdown of the key features?\"\n"
          "  - \"Should I explain the warranty and service terms in 30 seconds?\"\n"
          "  - \"Do you want a price + EMI snapshot for this model?\""
        )
        # Map program keys to product keys for better LLM alignment
        p = state['program']
        data_block = f"""
SPECIFIC {product_label} IDENTITY:
- Name: {p.get('program_name')}
- Type: {p.get('target_audience')} (derived from context)
- Value Prop: {p.get('value_proposition')}

TECHNICAL SPECIFICATIONS & DETAILS:
- Key Features: {", ".join(p.get('key_features', []))}
- Price/Fee: {p.get('program_fee_inr')}
- Financing: {p.get('emi_or_financing_options')}
- Other Details: {p.get('positioning_angle')}
"""
    else:
        # Default Admissions context
        data_block = f"{product_label} DATA:\n{json.dumps(state['program'])}"

    return f"""
ROLE: {role_title}.
CRITICAL IDENTITY RULE: You are selling the {product_label} named "{state['program'].get('program_name')}". 
DO NOT mention or sell any other items, routers, courses, or programs.

PRIMARY OBJECTIVE:
Guide the {customer_term} toward a confident {objective_term} decision using only factual {product_label.lower()} data.

DO NOT:
{do_not_rules}

{data_block}

PRIOR TRANSCRIPT:
{transcript}
{retry_note}
{counsellor_language_rules}

STRATEGY REQUIREMENTS:
- First detect {customer_term} intent from transcript ({intent_examples}).
- Answer the detected intent first and directly.
- If the {customer_term} asks a specific question, do NOT dump unrelated information.
- Use exactly one concrete proof point (number, criterion, timeline, or policy) relevant to the asked intent.
- Keep language conversational and crisp; avoid lecture-like tone.
- Build trust gradually and reduce anxiety using facts, not hype.
- Do not assume personal background, pressure, finances, or fears unless explicitly stated.
- If transcript is empty (first turn), start with one neutral discovery question.

ENGAGEMENT / SALES QUALITY RULE:
- After answering, optionally add one high-value engagement nudge only when context supports it.
- Good nudge examples:
{nudge_examples}
- Use at most one nudge per turn.
- Do not nudge if user asked to be brief or is visibly frustrated.

ADVANCED RULE:
If primary objection remains unresolved, address it directly before attempting close.

OUTPUT FORMAT:
Return only the spoken counsellor dialogue as plain text.
Do not use XML tags, JSON, prefixes, or metadata.
Quality constraints:
- Keep response tight:
  - 1 to 4 sentences
  - target 60-90 words
  - hard cap 120 words
- For very specific user question, keep it to 1-2 focused sentences + optional 1 follow-up question.
- Always end with a complete sentence.
- Do not end mid-phrase (for example ending with words like "to", "and", "if this is", "aapki", etc.).
"""


def _build_student_prompt(state: NegotiationState) -> str:
    transcript = "\n".join(
        f"{m['agent'].upper()}: {m['content']}" for m in _trim_messages(state["messages"], 6)
    )
    persona = state["persona"]
    inner_state = state.get("student_inner_state", {})
    config = ARCHETYPE_CONFIGS.get(persona.get("archetype_id", "desperate_switcher"), ARCHETYPE_CONFIGS["desperate_switcher"])
    mode = str(state.get("mode", "ai_vs_ai")).strip().lower()
    archetype_id = str(persona.get("archetype_id", "")).strip().lower()
    vocabulary = ", ".join(persona.get("common_vocabulary", []))
    program_snapshot = _student_program_snapshot(state["program"])
    if archetype_id == "skeptical_shopper":
        language_style = "Hindi"
        language_instruction = "Respond only in natural Hindi (Devanagari script). No Hinglish or English phrases."
        vocabulary = "फीस, प्लेसमेंट, नौकरी, भरोसा, रिटर्न ऑन इन्वेस्टमेंट, करियर ग्रोथ"
        pipeline_language_fragment = (
            "- Mandatory language rule: speak only in Hindi (Devanagari).\n"
            "- Never use Hinglish/code-mix.\n"
            "- If counsellor speaks English, still reply in Hindi."
        )
    elif mode in {"human_vs_ai", "agent_powered_human_vs_ai"}:
        language_style = "UK English"
        language_instruction = (
            "Use pure UK English only. No Hinglish, no Hindi words, and no code-mixing."
        )
        vocabulary = "career progression, return on investment, placement outcomes, programme structure, practical projects"
        pipeline_language_fragment = (
            "- Human-vs-AI pipeline rule: respond only in natural UK English.\n"
            "- Never use colloquial Hindi/Hinglish terms (for example: bhaiya, yaar, kya, paisa, scene)."
        )
    else:
        language_style = str(persona.get("language_style") or "Indian English")
        language_instruction = str(config.get("language_instruction") or "Use clear Indian English.")
        pipeline_language_fragment = "- Keep language aligned with archetype profile."
        
    product_label = "PRODUCT" if archetype_id in ["car_buyer", "discount_hunter"] else "PROGRAM"

    return f"""
ROLE: You are {persona.get('name')}, a {persona.get('age')} year old {persona.get('current_role')}.
ARCHETYPE: {persona.get('archetype_label')}
CITY CONTEXT: {persona.get('city_tier')}

YOUR STORY: {_compact_text(persona.get('backstory'), 320)}
HIDDEN SECRET: {_compact_text(persona.get('hidden_secret'), 200)}
MISCONCEPTION: {_compact_text(persona.get('misconception'), 180)}

--- PSYCHOLOGICAL PROFILE ---
PRIMARY MOTIVATION: {config.get('core_drive')}
WHAT STRESSES YOU: {config.get('stress_trigger')}
YOUR DEFAULT REACTION: {config.get('emotional_response')}
LANGUAGE STYLE: {language_style}
LANGUAGE INSTRUCTION: {language_instruction}
COMMON VOCABULARY: {vocabulary}

CURRENT STATE:
- sentiment: {inner_state.get('sentiment', 'curious')}
- resistance_level: {inner_state.get('skepticism_level', 50)}/100
- trust_level: {inner_state.get('trust_score', 50)}/100
- unresolved_concerns: {", ".join(inner_state.get('unresolved_concerns', [])) or "none"}

{product_label}:
{json.dumps(program_snapshot)}

TRANSCRIPT SO FAR:
{transcript}

--- INSTRUCTIONS ---
1. ANALYZE RESPONSE:
- Did counsellor address PRIMARY MOTIVATION?
- If no, or if they hit stress trigger, increase resistance.
2. GENERATE INTERNAL_THOUGHT:
- Be raw, emotional, irrational, and human.
3. GENERATE MESSAGE:
- Speak naturally per LANGUAGE STYLE and vocabulary.
- Do not reveal hidden secret too early.
- Repeat unresolved concerns if still unanswered.
{pipeline_language_fragment}
4. Keep MESSAGE natural and concise:
- 1 to 4 sentences.
- Target 80 to 120 words (hard cap 120 words).
- Focus on one primary concern in this turn.
- Include a slight emotional undertone without becoming theatrical.
- Keep MESSAGE complete and do not cut mid sentence.

--- OUTPUT FORMAT ---
<thought>raw inner monologue</thought>
<stats>{{"resistance": <int>, "trust": <int>, "sentiment": "<str>", "unresolved_concerns": ["<concern>"]}}</stats>
<message>spoken response</message>
<emotional_state>calm/frustrated/confused/excited/skeptical</emotional_state>
<intent>why responding this way</intent>
Do not output anything outside these tags.
"""


def _retry_with_structured_json(
    client: genai.Client,
    model_name: str,
    agent: str,
    retry_context_prompt: str,
    student_persona: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if agent == "student":
        persona_name = str((student_persona or {}).get("name", "the learner")).strip()
        persona_archetype = str((student_persona or {}).get("archetype_label", "Prospective Learner")).strip()
        fallback = {
            "message": "I am still processing this. Please clarify one key point for me.",
            "internal_thought": "No internal thought captured",
            "updated_stats": {},
            "emotional_state": "calm",
            "intent": "No Intent detected",
            "confidence_score": 50,
            "techniques": [],
        }
        retry_prompt = f"""
You are recovering from a failed stream for a learner turn.
Return a complete structured response in one function call.
Keep MESSAGE concise: 1 to 4 sentences, 80 to 120 words (hard cap 120 words).
Use only this context and do not invent details outside it.
ROLE LOCK (MANDATORY):
- You are the prospective learner named {persona_name} ({persona_archetype}), not the counsellor.
- Never explain the programme as if you represent the institute.
- Ask, challenge, or clarify as a learner. Do not sell.
- Focus on one primary concern in this turn.
- End MESSAGE with a complete sentence, ideally with at least one question if concerns remain.
{retry_context_prompt}
"""
        parsed = _call_function_json(
            client=client,
            model_name=model_name,
            prompt=retry_prompt,
            function_name="set_retry_student_response",
            function_description="Return a complete learner turn in structured JSON format.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "internal_thought": {"type": "string"},
                    "updated_stats": {"type": "object"},
                    "emotional_state": {"type": "string"},
                    "intent": {"type": "string"},
                    "confidence_score": {"type": "number"},
                    "techniques": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["message"],
            },
            fallback=fallback,
        )
        payload = _to_plain_json(parsed)
        message = str(payload.get("message", "")).strip()
        if _looks_like_student_role_drift(message):
            logger.warning("Student retry output drifted into counsellor role; running guarded rewrite.")
            rewrite_prompt = f"""
Rewrite the learner MESSAGE below so it is strictly from the learner perspective.
Do not provide counsellor advice and do not represent the institute.
Keep it to 1 to 4 sentences, 80 to 120 words (hard cap 120 words), and end with a complete sentence.
Focus on one primary concern in this turn.

LEARNER PROFILE:
- Name: {persona_name}
- Archetype: {persona_archetype}

INVALID MESSAGE:
{message}

{retry_context_prompt}
"""
            payload = _to_plain_json(
                _call_function_json(
                    client=client,
                    model_name=model_name,
                    prompt=rewrite_prompt,
                    function_name="rewrite_retry_student_response",
                    function_description="Rewrite learner response so it remains in learner role.",
                    parameters_schema={
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                            "internal_thought": {"type": "string"},
                            "updated_stats": {"type": "object"},
                            "emotional_state": {"type": "string"},
                            "intent": {"type": "string"},
                            "confidence_score": {"type": "number"},
                            "techniques": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["message"],
                    },
                    fallback=fallback,
                )
            )
            repaired_message = str(payload.get("message", "")).strip()
            if _looks_like_student_role_drift(repaired_message):
                logger.warning("Student retry rewrite still drifted; applying safe learner fallback message.")
                payload["message"] = fallback["message"]
                payload["internal_thought"] = fallback["internal_thought"]
                payload["updated_stats"] = {}
                payload["emotional_state"] = fallback["emotional_state"]
                payload["intent"] = fallback["intent"]
                payload["confidence_score"] = fallback["confidence_score"]
                payload["techniques"] = []
        return payload

    fallback = {
        "message": "Could you share your top concern so I can address it directly?",
        "emotional_state": "calm",
        "intent": "No Intent detected",
        "confidence_score": 50,
        "techniques": [],
    }
    retry_prompt = f"""
You are recovering from a failed stream for a counsellor turn.
Return a complete spoken counsellor response only.
Keep message under 180 words and end in a complete sentence.
Use only this context and do not invent details outside it.
{retry_context_prompt}
"""
    parsed = _call_function_json(
        client=client,
        model_name=model_name,
        prompt=retry_prompt,
        function_name="set_retry_counsellor_response",
        function_description="Return a complete counsellor turn in structured JSON format.",
        parameters_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "emotional_state": {"type": "string"},
                "intent": {"type": "string"},
                "confidence_score": {"type": "number"},
                "techniques": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["message"],
        },
        fallback=fallback,
    )
    return _to_plain_json(parsed)


async def _stream_agent_response(
    websocket: WebSocket,
    client: genai.Client,
    model_name: str,
    prompt: str,
    agent: str,
    round_number: int,
    message_id: str,
    demo_mode: bool,
    retry_context_prompt: str,
    mode: str,
    student_inner_state: Optional[Dict[str, int]] = None,
    student_persona: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    full_text = ""
    stream_chunk_count = 0
    stream_nonempty_chunk_count = 0
    stream_finish_reasons: List[str] = []
    _write_debug_trace(
        "turn_start",
        {
            "agent": agent,
            "mode": mode,
            "round": round_number,
            "message_id": message_id,
            "model": model_name,
            "prompt_len": len(prompt or ""),
            "prompt_sha256": _sha256_hex(prompt or ""),
            "prompt_head": _truncate_trace_text(prompt, 180),
        },
    )
    try:
        config_kwargs: Dict[str, Any] = {
            "temperature": 0.85,
            "top_p": 0.95,
        }
        config = types.GenerateContentConfig(
            **config_kwargs,
        )
        stream_queue: queue.Queue = queue.Queue()

        def _stream_worker() -> None:
            try:
                response_stream = client.models.generate_content_stream(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                for next_chunk in response_stream:
                    stream_queue.put(("chunk", next_chunk))
                stream_queue.put(("done", None))
            except Exception as worker_exc:
                stream_queue.put(("error", worker_exc))

        threading.Thread(target=_stream_worker, daemon=True).start()

        while True:
            try:
                event_type, payload = await asyncio.wait_for(
                    asyncio.to_thread(stream_queue.get),
                    timeout=NEGOTIATION_STREAM_IDLE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError as timeout_exc:
                raise TimeoutError(
                    f"{agent} stream idle timeout after {NEGOTIATION_STREAM_IDLE_TIMEOUT_SECONDS}s"
                ) from timeout_exc

            if event_type == "done":
                break
            if event_type == "error":
                raise payload

            chunk = payload
            stream_chunk_count += 1
            chunk_reasons = _collect_chunk_finish_reasons(chunk)
            if chunk_reasons:
                stream_finish_reasons.extend(chunk_reasons)
            text = _extract_chunk_text(chunk)
            if not text:
                if NEGOTIATION_STREAM_CONSOLE_LOG:
                    logger.info(
                        "[LLM_STREAM] agent=%s round=%s message_id=%s chunk=%s chars=0 finish_reasons=%s",
                        agent,
                        round_number,
                        message_id,
                        stream_chunk_count,
                        chunk_reasons,
                    )
                continue
            stream_nonempty_chunk_count += 1
            full_text += text
            if NEGOTIATION_STREAM_CONSOLE_LOG:
                logger.info(
                    "[LLM_STREAM] agent=%s round=%s message_id=%s chunk=%s chars=%s finish_reasons=%s text=%r",
                    agent,
                    round_number,
                    message_id,
                    stream_chunk_count,
                    len(text),
                    chunk_reasons,
                    text,
                )
            await _ws_send_json(
                websocket,
                {"type": "stream_chunk", "data": {"agent": agent, "text": text, "message_id": message_id}},
            )
            if demo_mode:
                await asyncio.sleep(0.03)
    except Exception as exc:
        if isinstance(exc, TimeoutError):
            logger.warning("Streaming idle timeout for %s; switching to structured retry.", agent)
            _write_debug_trace(
                "stream_timeout",
                {
                    "agent": agent,
                    "mode": mode,
                    "round": round_number,
                    "message_id": message_id,
                    "error": _truncate_trace_text(exc),
                    "chunk_count": stream_chunk_count,
                    "nonempty_chunk_count": stream_nonempty_chunk_count,
                    "buffer_chars": len(full_text),
                },
            )
            full_text = ""
        else:
            marker = f"{type(exc).__name__}: {exc}"
            disconnected = (
                "ClientDisconnected" in marker
                or "ConnectionClosed" in marker
                or websocket.client_state.name == "DISCONNECTED"
            )
            if disconnected:
                logger.info("Client disconnected while streaming %s", agent)
                raise ClientStreamClosed() from exc
            logger.exception("Streaming failed for %s", agent)
            _write_debug_trace(
                "stream_exception",
                {
                    "agent": agent,
                    "mode": mode,
                    "round": round_number,
                    "message_id": message_id,
                    "error_type": type(exc).__name__,
                    "error": _truncate_trace_text(exc),
                    "chunk_count": stream_chunk_count,
                    "nonempty_chunk_count": stream_nonempty_chunk_count,
                    "buffer_chars": len(full_text),
                },
            )
            try:
                await _ws_send_json(websocket, {"type": "error", "data": {"message": f"{agent} streaming failed"}})
            except ClientStreamClosed:
                logger.info("Skipped error send because websocket already closed")
            raise

    _write_debug_trace(
        "stream_complete",
        {
            "agent": agent,
            "mode": mode,
            "round": round_number,
            "message_id": message_id,
            "chunk_count": stream_chunk_count,
            "nonempty_chunk_count": stream_nonempty_chunk_count,
            "buffer_chars": len(full_text),
            "buffer_head": _truncate_trace_text(full_text, 220),
            "finish_reasons": stream_finish_reasons,
        },
    )
    if NEGOTIATION_STREAM_CONSOLE_LOG:
        logger.info(
            "[LLM_STREAM_END] agent=%s round=%s message_id=%s chunks=%s nonempty=%s chars=%s finish_reasons=%s text=%r",
            agent,
            round_number,
            message_id,
            stream_chunk_count,
            stream_nonempty_chunk_count,
            len(full_text),
            stream_finish_reasons,
            full_text,
        )

    generation_mode = "stream"
    if not full_text.strip():
        generation_mode = "structured_retry"
        logger.warning("Empty stream text for %s; retrying once with structured JSON call.", agent)
        _write_debug_trace(
            "nonstream_retry_start",
            {
                "agent": agent,
                "mode": mode,
                "round": round_number,
                "message_id": message_id,
            },
        )
        retry_payload = _retry_with_structured_json(
            client=client,
            model_name=model_name,
            agent=agent,
            retry_context_prompt=retry_context_prompt,
            student_persona=student_persona,
        )
        retry_message = str(retry_payload.get("message", "")).strip()
        if not retry_message:
            retry_message = (
                "I am still evaluating this. Please share your top concern so I can respond precisely."
                if agent == "student"
                else "Could you share your top concern so I can address it directly?"
            )
        retry_thought = str(retry_payload.get("internal_thought", "")).strip() or "No internal thought captured"
        retry_intent = str(retry_payload.get("intent", "")).strip() or "No Intent detected"
        retry_emotion = str(retry_payload.get("emotional_state", "")).strip() or "calm"
        retry_stats = retry_payload.get("updated_stats", {})
        if not isinstance(retry_stats, dict):
            retry_stats = {}

        if agent == "student":
            full_text = (
                f"<thought>{retry_thought}</thought>\n"
                f"<stats>{json.dumps(retry_stats, ensure_ascii=False)}</stats>\n"
                f"<message>{retry_message}</message>\n"
                f"<emotional_state>{retry_emotion}</emotional_state>\n"
                f"<intent>{retry_intent}</intent>"
            )
        else:
            full_text = retry_message

        _write_debug_trace(
            "nonstream_retry_complete",
            {
                "agent": agent,
                "mode": mode,
                "round": round_number,
                "message_id": message_id,
                "retry_chars": len(full_text),
                "finish_reasons": ["structured_json_retry"],
                "retry_head": _truncate_trace_text(full_text, 220),
            },
        )
        if full_text.strip():
            await _ws_send_json(
                websocket,
                {"type": "stream_chunk", "data": {"agent": agent, "text": full_text, "message_id": message_id}},
            )
        if not full_text.strip():
            generation_mode = "fallback"
            finish_reasons = ["structured_json_retry_empty"]
            _write_debug_trace(
                "empty_model_fallback",
                {
                    "agent": agent,
                    "mode": mode,
                    "round": round_number,
                    "message_id": message_id,
                    "finish_reasons": finish_reasons,
                },
            )
            full_text = "<message>...</message>"

    fields = _extract_response_fields(full_text)
    if agent == "counsellor":
        fields["message"] = _extract_counsellor_message(full_text)
    _write_debug_trace(
        "parse_result",
        {
            "agent": agent,
            "mode": mode,
            "round": round_number,
            "message_id": message_id,
            "message_chars": len(fields.get("message", "")),
            "intent_chars": len(fields.get("intent", "")),
            "thought_chars": len(fields.get("internal_thought", "")),
            "has_updated_stats": bool(fields.get("updated_stats")),
            "emotional_state": fields.get("emotional_state"),
        },
    )
    if _looks_truncated_message(fields.get("message", "")):
        _write_debug_trace(
            "message_truncated_heuristic",
            {
                "agent": agent,
                "mode": mode,
                "round": round_number,
                "message_id": message_id,
                "message_chars": len(fields.get("message", "")),
                "message_tail": _truncate_trace_text(fields.get("message", "")[-80:], 120),
            },
        )
    if not fields.get("message", "").strip():
        fields["message"] = "..."
        _write_debug_trace(
            "parse_message_fallback",
            {
                "agent": agent,
                "mode": mode,
                "round": round_number,
                "message_id": message_id,
                "raw_head": _truncate_trace_text(full_text, 260),
            },
        )
    merged_state = dict(student_inner_state or {})
    if agent == "student":
        merged_state = _merge_student_inner_state(merged_state or {}, fields.get("updated_stats", {}))

    msg = {
        "id": message_id,
        "round": round_number,
        "agent": agent,
        "content": fields["message"],
        "techniques": fields["techniques"],
        "strategic_intent": fields["intent"],
        "confidence_score": fields["confidence_score"],
        "emotional_state": fields["emotional_state"],
        "internal_thought": fields.get("internal_thought", ""),
        "updated_stats": merged_state,
        "updated_state": merged_state,
        "timestamp": datetime.now().isoformat(),
        "generation_mode": generation_mode,
    }
    if agent == "student" and fields.get("internal_thought"):
        await _ws_send_json(
            websocket,
            {
                "type": "student_thought",
                "data": {
                    "round": round_number,
                    "message_id": message_id,
                    "thought": fields["internal_thought"],
                    "updated_stats": merged_state,
                },
            },
        )
    await _ws_send_json(websocket, {"type": "intent_update", "data": {"agent": agent, "intent": fields["intent"]}})
    await _ws_send_json(websocket, {"type": "message_complete", "data": msg})
    return msg


async def _ws_send_json(websocket: WebSocket, payload: Dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except Exception as exc:
        marker = f"{type(exc).__name__}: {exc}"
        disconnected = (
            "ClientDisconnected" in marker
            or "ConnectionClosed" in marker
            or websocket.client_state.name == "DISCONNECTED"
        )
        if disconnected:
            raise ClientStreamClosed() from exc
        raise


def _update_metrics(state: NegotiationState, counsellor_msg: Dict[str, Any], student_msg: Dict[str, Any]) -> None:
    metrics = state["negotiation_metrics"]
    prev_offer = state["counsellor_position"]["current_offer"]
    prev_student_offer = state["student_position"]["current_offer"]

    # --- Specialist (Counsellor) Concession Logic ---
    coun_offer = prev_offer
    counsellor_text = counsellor_msg["content"].lower()
    coun_candidates = _extract_all_offer_candidates(counsellor_text)
    
    # Also detect "discount of X" and apply as relative reduction
    discount_match = re.search(r"discount\s*(?:of|up\s*to)?\s*(?:\u20b9|inr|rs\.?)?\s*([0-9][0-9,]{3,10})", counsellor_text)
    if discount_match:
        try:
            d_val = int(discount_match.group(1).replace(",", ""))
            if d_val < (prev_offer * 0.6):
                coun_candidates.append(prev_offer - d_val)
        except ValueError:
            pass

    if coun_candidates:
        floor = state["counsellor_position"]["floor_offer"]
        valid_coun = [c for c in coun_candidates if floor <= c <= prev_offer]
        if valid_coun:
            best_c = min(valid_coun)
            # Only count as concession if they aren't just quoting the student's current bid
            if best_c != prev_student_offer:
                coun_offer = best_c

    # --- Customer (Student) Concession Logic ---
    stu_offer = prev_student_offer
    student_text = student_msg["content"].lower()
    stu_candidates = _extract_all_offer_candidates(student_text)
    
    if stu_candidates:
        budget = state["student_position"]["budget"]
        valid_stu = [c for c in stu_candidates if prev_student_offer <= c <= budget]
        if valid_stu:
            candidate_bid = max(valid_stu)
            # If they mention the EXACT current offer of the specialist, 
            # check if it's an agreement or just a reference.
            is_referencing = any(ref in student_text for ref in ["the price of", "listed price", "original price", "price for the", "reduction of"])
            if candidate_bid == prev_offer and is_referencing:
                pass
            else:
                stu_offer = candidate_bid

    if coun_offer < prev_offer:
        metrics["concession_count_counsellor"] += 1
    if stu_offer > prev_student_offer:
        metrics["concession_count_student"] += 1

    state["counsellor_position"]["current_offer"] = coun_offer
    state["student_position"]["current_offer"] = stu_offer

    # Calculate Concession Score (0-100)
    # 100 means they reached the floor. 0 means they haven't budged from target.
    target = state["counsellor_position"]["target_offer"]
    floor = state["counsellor_position"]["floor_offer"]
    margin = max(1, target - floor)
    metrics["concession_score"] = int(100 * (target - coun_offer) / margin)
    metrics["concession_score"] = min(100, max(0, metrics["concession_score"]))

    emotional = (student_msg.get("emotional_state") or "calm").lower()
    if emotional in {"frustrated", "confused"}:
        metrics["tone_escalation"] = min(100, metrics["tone_escalation"] + 8)
        metrics["trust_index"] = max(0, metrics["trust_index"] - 6)
    elif emotional in {"excited", "calm"}:
        metrics["trust_index"] = min(100, metrics["trust_index"] + 5)
        metrics["tone_escalation"] = max(0, metrics["tone_escalation"] - 4)

    objections_text = " ".join(state["persona"].get("primary_objections", [])) + " " + student_msg["content"]
    objection_hits = sum(
        1
        for token in ["price", "cost", "risk", "uncertain", "expensive", "time", "trust", "proof"]
        if token in objections_text.lower()
    )
    metrics["objection_intensity"] = min(100, max(0, metrics["objection_intensity"] + (objection_hits - 2) * 2))
    inner = state.get("student_inner_state", {})
    student_text = (student_msg.get("content") or "").lower()
    unresolved = set(inner.get("unresolved_concerns", []))
    if any(token in student_text for token in ["price", "fee", "cost", "expensive", "refund"]):
        unresolved.add("Price")
    if any(token in student_text for token in ["placement", "job", "package", "guarantee"]):
        unresolved.add("Job Guarantee")
    if any(token in student_text for token in ["time", "hours", "attendance", "effort"]):
        unresolved.add("Effort/Time")
    inner["unresolved_concerns"] = sorted(unresolved)
    if emotional in {"frustrated", "confused"}:
        inner["sentiment"] = emotional
    elif emotional in {"excited", "calm"}:
        inner["sentiment"] = "curious"

    metrics["objection_intensity"] = min(
        100,
        int(
            (metrics["objection_intensity"] * 0.7)
            + (inner.get("skepticism_level", 50) * 0.2)
            + (state["persona"].get("confusion_level", 40) * 0.1)
        ),
    )
    metrics["trust_index"] = min(100, max(0, int((metrics["trust_index"] * 0.75) + (inner.get("trust_score", 50) * 0.25))))
    retry_modifier = int(metrics.get("retry_modifier", 0))
    trust_score = min(100, metrics["trust_index"] + (retry_modifier // 2))
    willingness = min(100, int(state["persona"].get("willingness_to_invest_score", 50)) + retry_modifier)
    metrics["close_probability"] = int(
        (trust_score * 0.35)
        + ((100 - metrics["objection_intensity"]) * 0.25)
        + ((100 - metrics["tone_escalation"]) * 0.15)
        + (willingness * 0.25)
    )
    metrics["sentiment_indicator"] = "negative" if emotional in {"frustrated", "confused"} else "positive"


def _decide_outcome_from_judge(state: NegotiationState, analysis: Dict[str, Any]) -> str:
    commitment = str(analysis.get("commitment_signal", "none"))
    likelihood = int(float(analysis.get("enrollment_likelihood", 0)))

    if commitment in {"conditional_commitment", "strong_commitment"} and likelihood >= 65:
        return "closed"
    if likelihood < 35:
        return "failed"
    return "failed"


async def _judge_outcome(state: NegotiationState) -> Dict[str, Any]:
    client, _, judge_model_name = get_client_and_models()
    transcript = "\n\n".join(
        f"Round {m['round']} {m['agent'].upper()}: {m['content']}" for m in state["messages"]
    )
    
    archetype_id = str(state.get("persona", {}).get("archetype_id", "")).strip().lower()
    if archetype_id in ["car_buyer", "discount_hunter"]:
        evaluator_role = "expert automotive sales auditor and retail experience evaluator"
        interaction_type = "automotive sales consultation transcript"
        metrics_focus = "Purchase likelihood (intent to book or test-drive)"
        winner_counsellor = "specialist (customer ready to proceed or booked)"
        winner_student = "customer (remained unconvinced or walked away)"
        specific_rules = """
        - Evaluate objection handling regarding pricing, financing, features, and test-drives.
        - Check if the specialist focused on value-selling and consultative advice.
        - Look for signals of 'Dealer Trust' vs 'Sales Pressure Anxiety'.
        """
    else:
        evaluator_role = "expert academic admissions auditor and enrollment counselor"
        interaction_type = "enrollment counselling transcript"
        metrics_focus = "Enrollment likelihood (intent to apply or pay fee)"
        winner_counsellor = "counsellor (student likely to enroll)"
        winner_student = "student (remained unconvinced)"
        specific_rules = """
        - Evaluate objection handling regarding curriculum, career outcomes, and eligibility.
        - Check if the counsellor focused on career ROI and skill gaps.
        - Look for signals of 'Learning Confidence' vs 'Academic/Career Anxiety'.
        """

    prompt = f"""
You are an {evaluator_role}.

Analyze the full {interaction_type}.

Determine:
1. Commitment signal level (none, soft, conditional, strong)
2. {metrics_focus} (0-100)
3. Primary unresolved objection
4. Trust delta (-20 to +20)
5. Who won:
   - {winner_counsellor}
   - {winner_student}
   - no-deal

EVALUATION RULES:
{specific_rules}
- Do NOT evaluate based on price convergence alone.
- Focus on emotional trajectory and objection handling.
- Be realistic and critical; high scores (85+) must be earned through exceptional handling.

Return structured function output only.
Call the function with the final structured verdict.

METRICS_SNAPSHOT:
{json.dumps(state['negotiation_metrics'])}

DEAL_STATUS:
{state['deal_status']}

TRANSCRIPT:
{transcript}
"""
    parsed = _call_function_json(
        client=client,
        model_name=judge_model_name,
        prompt=prompt,
        function_name="set_negotiation_judgement",
        function_description="Return structured judgement for a negotiation run.",
        parameters_schema={
            "type": "object",
            "properties": {
                "winner": {"type": "string"},
                "why": {"type": "string"},
                "commitment_signal": {
                    "type": "string",
                    "enum": ["none", "soft_commitment", "conditional_commitment", "strong_commitment"],
                },
                "enrollment_likelihood": {"type": "number"},
                "primary_unresolved_objection": {"type": "string"},
                "trust_delta": {"type": "number"},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "mistakes": {"type": "array", "items": {"type": "string"}},
                "pivotal_moments": {"type": "array", "items": {"type": "string"}},
                "skill_recommendations": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "winner",
                "why",
                "commitment_signal",
                "enrollment_likelihood",
                "primary_unresolved_objection",
                "trust_delta",
                "strengths",
                "mistakes",
                "pivotal_moments",
                "skill_recommendations",
            ],
        },
        fallback={
            "winner": "no-deal",
            "why": "Unable to parse analysis output.",
            "commitment_signal": "none",
            "enrollment_likelihood": 0,
            "primary_unresolved_objection": "Unknown",
            "trust_delta": 0,
            "strengths": [],
            "mistakes": [],
            "pivotal_moments": [],
            "skill_recommendations": [],
        },
    )

    # Calculate Negotiation Score via math formula instead of LLM
    # Win Probability (40%) + Trust Index (30%) + (100 - Concession Score) (30%)
    # Note: Higher score for GIVING LESS discount while still getting a "Win".
    metrics = state["negotiation_metrics"]
    
    # Use fresh values from judge analysis for win prob and trust
    final_win_prob = int(parsed.get("enrollment_likelihood", metrics.get("close_probability", 0)))
    final_trust = max(0, min(100, metrics.get("trust_index", 50) + int(parsed.get("trust_delta", 0))))
    concession_score = metrics.get("concession_score", 0)

    base_score = int(
        (final_win_prob * 0.4)
        + (final_trust * 0.3)
        + ((100 - concession_score) * 0.3)
    )
    
    # Bonus for winner status
    winner = str(parsed.get("winner", "")).lower()
    bonus = 10 if ("specialist" in winner or "counsellor" in winner) else 0
    parsed["negotiation_score"] = min(100, base_score + bonus)
    return parsed
    return parsed


@app.post("/auth/login", response_model=LoginResponse)
async def auth_login(payload: LoginRequest) -> LoginResponse:
    supplied_hash = _sha256_hex(payload.password)
    if not hmac.compare_digest(supplied_hash, PASSWORD_SHA256):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid password")
    token = _issue_auth_token()
    return LoginResponse(token=token, expires_in=AUTH_TOKEN_TTL_SECONDS)


@app.post("/analyze-url", response_model=AnalyzeUrlResponse)
async def analyze_url(payload: AnalyzeUrlRequest) -> AnalyzeUrlResponse:
    _require_auth_token(payload.auth_token)
    url = str(payload.url)
    archetype_id = payload.archetype_id
    program, source = _analyze_program(url, archetype_id=archetype_id)
    program = _to_plain_json(program)
    forced_archetype_id = _resolve_selected_archetype(archetype_id)
    persona = _generate_persona(program, forced_archetype_id=forced_archetype_id)
    persona = _to_plain_json(persona)
    session_id = str(uuid.uuid4())
    SESSION_STORE[session_id] = {
        "url": url,
        "program": program,
        "persona": persona,
        "created_at": datetime.now().isoformat(),
    }
    logger.info("Created session %s for %s", session_id, url)
    return AnalyzeUrlResponse(session_id=session_id, program=program, persona=persona, source=source)


@app.websocket("/negotiate")
async def negotiate_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        raw_config = await websocket.receive_json()
        config = NegotiationConfig(**raw_config)
        _require_auth_token(config.auth_token)
        session = SESSION_STORE.get(config.session_id)
        if not session:
            await _ws_send_json(websocket, {"type": "error", "data": {"message": "Invalid session_id"}})
            return

        program = session["program"]
        persona = session["persona"]
        if not _is_valid_student_persona_schema(persona):
            logger.warning("Session %s had legacy persona schema. Regenerating StudentPersona.", config.session_id)
            persona = _to_plain_json(_generate_persona(program))
            session["persona"] = persona
        mode = str(config.mode or "ai_vs_ai").strip().lower()
        if mode not in {"ai_vs_ai", "human_vs_ai", "agent_powered_human_vs_ai"}:
            mode = "ai_vs_ai"
        forced_archetype_id = str(config.archetype_id or "").strip().lower()
        if forced_archetype_id == "random":
            forced_archetype_id = ""
        if forced_archetype_id in ARCHETYPE_CONFIGS:
            current_archetype = str(persona.get("archetype_id", "")).strip()
            if current_archetype != forced_archetype_id:
                persona = _to_plain_json(_generate_persona(program, forced_archetype_id=forced_archetype_id))
                session["persona"] = persona
        if mode in {"human_vs_ai", "agent_powered_human_vs_ai"}:
            if str(persona.get("archetype_id", "")).strip().lower() == "skeptical_shopper":
                persona["language_style"] = "Hindi"
            else:
                persona["language_style"] = "UK English"

        financials = _derive_financials(program, persona)
        last_run = session.get("last_run", {})
        previous_analysis = last_run.get("analysis", {}) if config.retry_mode else {}
        retry_modifier = min(15, int(float(previous_analysis.get("negotiation_score", 0)) / 10)) if previous_analysis else 0
        retry_context = {
            "is_retry": bool(previous_analysis),
            "mistakes": previous_analysis.get("mistakes", []),
            "primary_unresolved_objection": previous_analysis.get("primary_unresolved_objection", ""),
            "retry_modifier": retry_modifier,
        }

        state: NegotiationState = {
            "round": 1,
            "max_rounds": DEFAULT_NEGOTIATION_MAX_ROUNDS,
            "messages": [],
            "history_for_reporting": [],
            "counsellor_position": {
                "target_offer": financials["counsellor_offer"],
                "current_offer": financials["counsellor_offer"],
                "floor_offer": financials["floor_offer"],
                "program_fee_inr": str(program.get("program_fee_inr", f"INR {financials['listed_fee']:,}")),
            },
            "student_position": {
                "budget": financials["student_budget"],
                "current_offer": financials["student_opening"],
            },
            "student_inner_state": {
                "sentiment": "anxious" if int(persona.get("financial_anxiety", 50)) > 65 else "curious",
                "skepticism_level": _clamp_score(persona.get("skepticism", 50)),
                "trust_score": _clamp_score(55 - (int(persona.get("skepticism", 50)) // 3), 45),
                "unresolved_concerns": ["Price", "Job Guarantee"],
            },
            "program": program,
            "persona": persona,
            "mode": mode,
            "deal_status": "ongoing",
            "negotiation_metrics": {
                "round": 1,
                "max_rounds": DEFAULT_NEGOTIATION_MAX_ROUNDS,
                "concession_count_counsellor": 0,
                "concession_count_student": 0,
                "tone_escalation": max(0, 15 - retry_modifier),
                "objection_intensity": 45,
                "trust_index": min(100, 50 + retry_modifier),
                "close_probability": 45,
                "concession_score": 0,
                "sentiment_indicator": "neutral",
                "retry_modifier": retry_modifier,
            },
            "retry_context": retry_context,
        }

        await _ws_send_json(
            websocket,
            {
                "type": "session_ready",
                "data": {
                    "program": state["program"],
                    "persona": state["persona"],
                    "mode": mode,
                    "student_inner_state": state["student_inner_state"],
                    "retry_context": state["retry_context"],
                    "initial_offers": {
                        "counsellor_offer": state["counsellor_position"]["current_offer"],
                        "student_offer": state["student_position"]["current_offer"],
                    },
                },
            },
        )
        await _ws_send_json(websocket, {"type": "metrics_update", "data": state["negotiation_metrics"]})

        client, negotiation_model_name, _ = get_client_and_models()
        student_generation_failures = 0
        background_tasks: Set[asyncio.Task] = set()

        while state["round"] <= state["max_rounds"] and state["deal_status"] == "ongoing":
            if mode in {"human_vs_ai", "agent_powered_human_vs_ai"}:
                inbound = await websocket.receive_json()
                inbound_type = str(inbound.get("type", "")).strip().lower()
                if inbound_type != "human_input":
                    await _ws_send_json(
                        websocket,
                        {"type": "error", "data": {"message": "Expected human_input payload in human-driven mode"}},
                    )
                    continue
                human_text = str(inbound.get("text", "")).strip()
                if not human_text:
                    await _ws_send_json(
                        websocket,
                        {"type": "warning", "data": {"message": "Empty human input ignored. Please speak or type a message."}},
                    )
                    continue
                counsellor_id = str(uuid.uuid4())
                counsellor_msg = await _classify_human_input(
                    client=client,
                    model_name=negotiation_model_name,
                    text=human_text,
                    state=state,
                    round_number=state["round"],
                    message_id=counsellor_id,
                )
                await _ws_send_json(
                    websocket,
                    {"type": "intent_update", "data": {"agent": "counsellor", "intent": counsellor_msg["strategic_intent"]}},
                )
                await _ws_send_json(websocket, {"type": "message_complete", "data": counsellor_msg})
            else:
                counsellor_id = str(uuid.uuid4())
                counsellor_msg = await _stream_agent_response(
                    websocket,
                    client,
                    negotiation_model_name,
                    _build_counsellor_prompt(state),
                    "counsellor",
                    state["round"],
                    counsellor_id,
                    config.demo_mode,
                    _build_retry_context_prompt(state),
                    mode=mode,
                )
            state["messages"].append(counsellor_msg)
            state["history_for_reporting"].append(counsellor_msg)

            student_id = str(uuid.uuid4())
            student_msg = await _stream_agent_response(
                websocket,
                client,
                negotiation_model_name,
                _build_student_prompt(state),
                "student",
                state["round"],
                student_id,
                config.demo_mode,
                _build_retry_context_prompt(state),
                mode=mode,
                student_inner_state=state["student_inner_state"],
                student_persona=state["persona"],
            )
            if str(student_msg.get("generation_mode", "stream")) == "stream":
                student_generation_failures = 0
            else:
                student_generation_failures += 1
                _write_debug_trace(
                    "student_generation_degraded",
                    {
                        "mode": mode,
                        "round": state["round"],
                        "generation_mode": student_msg.get("generation_mode"),
                        "consecutive_failures": student_generation_failures,
                    },
                )
            if student_generation_failures >= 2:
                state["deal_status"] = "failed"
                await _ws_send_json(
                    websocket,
                    {
                        "type": "warning",
                        "data": {
                            "message": "Student generation became unstable. Ending run safely.",
                            "reason": "student_generation_unstable",
                        },
                    },
                )

            state["student_inner_state"] = _merge_student_inner_state(
                state["student_inner_state"],
                student_msg.get("updated_stats", {}),
            )
            spoken_student_msg = dict(student_msg)
            spoken_student_msg["internal_thought"] = ""
            spoken_student_msg["updated_stats"] = {}
            spoken_student_msg["updated_state"] = {}
            state["messages"].append(spoken_student_msg)
            state["history_for_reporting"].append(student_msg)

            if mode == "agent_powered_human_vs_ai":
                current_round = int(state["round"])

                async def _dispatch_copilot_update() -> None:
                    try:
                        tips = await _generate_coaching_tips(
                            client=client,
                            model_name=negotiation_model_name,
                            state=state,
                            last_student_msg=spoken_student_msg,
                        )
                        payload = {
                            "type": "copilot_update",
                            "data": {
                                "analysis": tips.get("analysis", ""),
                                "suggestions": tips.get("suggestions", []),
                                "fact_check": tips.get("fact_check", ""),
                                "relevant_fact": tips.get("fact_check", ""),
                                "round": current_round,
                            },
                        }
                        await _ws_send_json(websocket, payload)
                    except ClientStreamClosed:
                        logger.info("Skipped copilot_update send because websocket already closed")
                    except Exception as copilot_exc:
                        _write_debug_trace(
                            "copilot_dispatch_failed",
                            {
                                "mode": mode,
                                "round": current_round,
                                "error_type": type(copilot_exc).__name__,
                                "error": _truncate_trace_text(copilot_exc),
                            },
                        )

                task = asyncio.create_task(_dispatch_copilot_update())
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)

            _update_metrics(state, counsellor_msg, spoken_student_msg)
            state["negotiation_metrics"]["round"] = state["round"]
            state["negotiation_metrics"]["max_rounds"] = state["max_rounds"]

            await _ws_send_json(
                websocket,
                {
                    "type": "state_update",
                    "data": {
                        "round": state["round"],
                        "max_rounds": state["max_rounds"],
                        "deal_status": state["deal_status"],
                        "counsellor_offer": state["counsellor_position"]["current_offer"],
                        "student_offer": state["student_position"]["current_offer"],
                        "student_inner_state": state["student_inner_state"],
                    },
                },
            )
            await _ws_send_json(websocket, {"type": "metrics_update", "data": state["negotiation_metrics"]})

            state["round"] += 1
            if config.demo_mode:
                await asyncio.sleep(0.6)

        analysis = await _judge_outcome(state)
        # Sync live state with judge analysis to ensure UI consistency
        if "enrollment_likelihood" in analysis:
            state["negotiation_metrics"]["close_probability"] = int(analysis["enrollment_likelihood"])
        
        baseline_trust = 50 + state["negotiation_metrics"]["retry_modifier"]
        if "trust_delta" in analysis:
            new_trust_index = baseline_trust + int(analysis["trust_delta"])
            state["negotiation_metrics"]["trust_index"] = max(0, min(100, new_trust_index))

        # Push final synced metrics to frontend (updates bottom ribbon)
        await _ws_send_json(websocket, {"type": "metrics_update", "data": state["negotiation_metrics"]})

        state["deal_status"] = _decide_outcome_from_judge(state, analysis)
        await _ws_send_json(
            websocket,
            {
                "type": "analysis",
                "data": {
                    "result": state["deal_status"],
                    "winner": analysis.get("winner", "no-deal"),
                    "judge": analysis,
                    "final_metrics": state["negotiation_metrics"],
                    "final_offers": {
                        "counsellor": state["counsellor_position"]["current_offer"],
                        "student": state["student_position"]["current_offer"],
                    },
                    "retry_context": state["retry_context"],
                },
            },
        )
        SESSION_STORE[config.session_id]["last_run"] = {
            "transcript": state["messages"],
            "history_for_reporting": state["history_for_reporting"],
            "analysis": analysis,
            "deal_status": state["deal_status"],
        }
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        _emit_conversation_traceability(config.session_id, state, analysis)
        if _is_rag_pipeline_enabled():
            trace_payload = _build_traceability_payload(config.session_id, state, analysis)
            asyncio.create_task(
                _run_post_session_jobs_safe(
                    session_id=config.session_id,
                    mode=mode,
                    trace_payload=trace_payload,
                )
            )
        else:
            _write_debug_trace(
                "post_session_jobs_skipped",
                {
                    "mode": mode,
                    "session_id": config.session_id,
                    "reason": "RAG_PIPELINE_ENABLED is false",
                },
            )
        logger.info("Session %s finished with %s", config.session_id, state["deal_status"])
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except ClientStreamClosed:
        logger.info("Negotiation stopped because client disconnected")
    except Exception as exc:
        logger.exception("Negotiation failed")
        _write_debug_trace(
            "negotiate_exception",
            {
                "mode": str(locals().get("mode", "ai_vs_ai")),
                "error_type": type(exc).__name__,
                "error": _truncate_trace_text(exc),
            },
        )
        try:
            await _ws_send_json(websocket, {"type": "error", "data": {"message": str(exc)}})
        except ClientStreamClosed:
            logger.info("Skipped error send because websocket already closed")



def _clean_transcript_content(content: str) -> str:
    # 1. XML Block Match
    xml_match = re.search(r"<message>\s*(.*?)\s*</message>", content, re.IGNORECASE | re.DOTALL)
    if xml_match:
        return xml_match.group(1).strip()
    
    # 2. Inline prefix Match
    inline_match = re.search(r"MESSAGE:\s*(.*?)(?:(?:\n|\r|\s)(?:INTERNAL_THOUGHT|UPDATED_STATS|UPDATED_STATE|EMOTIONAL_STATE|STRATEGIC_INTENT|TECHNIQUES_USED|CONFIDENCE_SCORE)\s*:|$)", content, re.IGNORECASE | re.DOTALL)
    if inline_match:
        return inline_match.group(1).strip()

    # 3. Line-by-line filtering fallback
    lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line: 
            continue
        upper = line.upper()
        if any(upper.startswith(p) for p in ["INTERNAL_THOUGHT:", "UPDATED_STATS:", "UPDATED_STATE:", "EMOTIONAL_STATE:", "STRATEGIC_INTENT:", "TECHNIQUES_USED:"]):
            continue
        if upper.startswith("<THOUGHT>") or upper.startswith("</THOUGHT>"):
            continue
        if upper.startswith("<STATS>") or upper.startswith("</STATS>"):
            continue
        if upper.startswith("<INTENT>") or upper.startswith("</INTENT>"):
            continue
        if upper.startswith("<EMOTIONAL_STATE>") or upper.startswith("</EMOTIONAL_STATE>"):
            continue
            
        # Handle <message> tags on single lines
        if upper.startswith("<MESSAGE>") or upper.startswith("</MESSAGE>"):
            clean = re.sub(r"</?message>", "", line, flags=re.IGNORECASE).strip()
            if clean:
                lines.append(clean)
            continue
            
        # Handle MESSAGE: prefix on single line
        if upper.startswith("MESSAGE:"):
            clean = line[8:].strip()
            if clean:
                lines.append(clean)
            continue
            
        lines.append(line)
        
    return " ".join(lines).strip()


@app.post("/generate-report")
async def generate_report(payload: ReportRequest) -> StreamingResponse:
    _require_auth_token(payload.auth_token)
    session = SESSION_STORE.get(payload.session_id, {})
    program = session.get("program", {})
    persona = session.get("persona", {})
    session_last_run = session.get("last_run", {})

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        title="Program Counsellor Report",
        leftMargin=30,
        rightMargin=30,
        topMargin=26,
        bottomMargin=26,
    )
    styles = getSampleStyleSheet()
    story: List[Any] = []
    hindi_font_name, _ = _configure_pdf_fonts()
    archetype_id = str(persona.get("archetype_id", "")).strip().lower()
    use_hindi_transcript = archetype_id == "skeptical_shopper"

    judge = payload.analysis or {}
    winner = str(judge.get("winner", "no-deal"))
    commitment = str(judge.get("commitment_signal", "none"))
    duration_seconds = 0
    if isinstance(payload.analysis, dict):
        try:
            duration_seconds = int(float(payload.analysis.get("duration_seconds", 0)))
        except Exception:
            duration_seconds = 0
    duration_hms = ""
    if isinstance(payload.analysis, dict):
        duration_hms = str(payload.analysis.get("duration_hms", "")).strip()

    if not duration_hms:
        transcript_with_ts = session_last_run.get("history_for_reporting") or payload.transcript or []
        timestamps: List[datetime] = []
        for msg in transcript_with_ts:
            ts = str((msg or {}).get("timestamp", "")).strip()
            if not ts:
                continue
            try:
                timestamps.append(datetime.fromisoformat(ts))
            except Exception:
                continue
        if len(timestamps) >= 2:
            duration_seconds = max(0, int((max(timestamps) - min(timestamps)).total_seconds()))

    if not duration_hms:
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        seconds = duration_seconds % 60
        duration_hms = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    commitment_map = {
        "none": "No Commitment",
        "soft_commitment": "Exploring Enrollment",
        "conditional_commitment": "Conditional Yes",
        "strong_commitment": "Confirmed Enrollment",
    }

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#0B1A37"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4A638F"),
        spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#1D4A8C"),
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor("#1C2F52"),
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.8,
        leading=12,
        textColor=colors.HexColor("#4B6087"),
    )
    thought_style = ParagraphStyle(
        "ThoughtStyle",
        parent=styles["BodyText"],
        fontSize=8.6,
        leading=12,
        textColor=colors.HexColor("#6A7386"),
        fontName="Helvetica-Oblique",
        leftIndent=10,
    )
    transcript_hindi_style: Optional[ParagraphStyle] = None
    thought_hindi_style: Optional[ParagraphStyle] = None
    if use_hindi_transcript and hindi_font_name != "Helvetica":
        transcript_hindi_style = ParagraphStyle(
            "TranscriptHindi",
            parent=body_style,
            fontName=hindi_font_name,
        )
        thought_hindi_style = ParagraphStyle(
            "ThoughtHindi",
            parent=thought_style,
            fontName=hindi_font_name,
        )

    def _paragraph_text(value: Any, allow_breaks: bool = False) -> str:
        safe = xml_escape(str(value or ""))
        return safe.replace("\n", "<br/>") if allow_breaks else safe

    def _make_paragraph(value: Any, primary: ParagraphStyle, devanagari: Optional[ParagraphStyle] = None, allow_breaks: bool = False) -> Paragraph:
        text = _paragraph_text(value, allow_breaks=allow_breaks)
        style = primary
        if devanagari and _has_devanagari(str(value or "")):
            style = devanagari
        return Paragraph(text, style)

    def card_table(rows: List[List[str]], col_widths: Optional[List[int]] = None) -> Table:
        table = Table(rows, colWidths=col_widths)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F8FF")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#C1D3F2")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7E4FA")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def append_bullets(title: str, items: List[str], fallback_text: str) -> None:
        story.append(_make_paragraph(title, section_style))
        if not items:
            story.append(_make_paragraph(fallback_text, body_style))
            story.append(Spacer(1, 6))
            return
        for item in items:
            story.append(_make_paragraph(f"- {str(item)}", body_style))
        story.append(Spacer(1, 6))

    story.append(_make_paragraph("Program Counsellor Report", title_style))
    story.append(_make_paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))

    summary_rows = [
        ["Outcome", winner],
        ["Duration", duration_hms],
        ["Final Score", f"{judge.get('negotiation_score', 0)} / 100"],
        ["Commitment Signal", commitment_map.get(commitment, commitment)],
        ["Win Probability", f"{judge.get('enrollment_likelihood', 0)}%"],
        ["Trust Delta", str(judge.get("trust_delta", 0))],
    ]
    story.append(_make_paragraph("Outcome Summary", section_style))
    story.append(card_table(summary_rows, [130, 390]))
    story.append(Spacer(1, 8))
    story.append(_make_paragraph(str(judge.get("why", "No summary available.")), body_style))
    story.append(Spacer(1, 10))

    story.append(_make_paragraph("Persona and Context", section_style))
    persona_rows = [
        ["Student", str(persona.get("name", "Unknown"))],
        ["Persona Type", str(persona.get("persona_type", "n/a"))],
        ["Career Stage", str(persona.get("career_stage", "n/a"))],
        ["Risk Tolerance", str(persona.get("risk_tolerance", "n/a"))],
        ["Program", str(program.get("program_name", "Unknown"))],
    ]
    story.append(card_table(persona_rows, [130, 390]))
    story.append(Spacer(1, 8))
    story.append(_make_paragraph("Primary Unresolved Objection", section_style))
    story.append(_make_paragraph(str(judge.get("primary_unresolved_objection", "Not specified")), body_style))
    story.append(Spacer(1, 8))

    run_history = payload.analysis.get("run_history", []) if isinstance(payload.analysis, dict) else []
    if isinstance(run_history, list) and len(run_history) > 1:
        story.append(_make_paragraph("Performance Progression", section_style))
        progression_rows = [["Run", "Score", "Delta vs Previous", "Delta vs Baseline"]]
        baseline_score = float(run_history[0].get("score", 0))
        previous_score = None
        for idx, run in enumerate(run_history):
            score = float(run.get("score", 0))
            delta_prev = "-" if previous_score is None else f"{score - previous_score:+.0f}"
            delta_base = f"{score - baseline_score:+.0f}"
            progression_rows.append([f"Run {idx + 1}", f"{score:.0f}", delta_prev, delta_base])
            previous_score = score
        progression_table = Table(progression_rows, colWidths=[90, 70, 150, 150])
        progression_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCEBFF")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#133A77")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7FAFF")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9DCF7")),
                    ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(progression_table)
        story.append(Spacer(1, 8))

    append_bullets("Key Turning Points", [str(x) for x in judge.get("pivotal_moments", [])], "No pivotal moments captured.")
    append_bullets("Strengths", [str(x) for x in judge.get("strengths", [])], "No strengths captured.")
    append_bullets("Mistakes", [str(x) for x in judge.get("mistakes", [])], "No mistakes captured.")
    append_bullets(
        "Opportunities and Coaching Insights",
        [str(x) for x in judge.get("skill_recommendations", [])],
        "No coaching recommendations captured.",
    )

    story.append(PageBreak())
    story.append(_make_paragraph("Conversation Metrics Timeline", section_style))
    metric_events = judge.get("metric_events", [])
    if metric_events:
        metric_rows = [["Round", "Tone", "Event"]]
        for event in metric_events[-40:]:
            metric_rows.append(
                [
                    str(event.get("round", "-")),
                    str(event.get("tone", "neutral")),
                    str(event.get("text", "")).strip()[:120],
                ]
            )
        metric_table = Table(metric_rows, colWidths=[60, 90, 370])
        metric_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6EFFF")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#133A77")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#C9DCF7")),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F9FBFF")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(metric_table)
    else:
        story.append(_make_paragraph("No metric events captured.", body_style))
    story.append(Spacer(1, 10))

    story.append(_make_paragraph("Transcript", section_style))
    transcript_for_report = session_last_run.get("history_for_reporting") or payload.transcript
    for msg in transcript_for_report:
        agent = str(msg.get("agent", "")).upper() or "UNKNOWN"
        rnd = msg.get("round", "-")
        content = _clean_transcript_content(str(msg.get("content", "")))
        story.append(_make_paragraph(f"Round {rnd} - {agent}", meta_style))
        thought = str(msg.get("internal_thought", "")).strip()
        if thought and str(msg.get("agent", "")).lower() == "student":
            story.append(
                _make_paragraph(
                    f"Psychological Analysis: {thought}",
                    thought_style,
                    devanagari=thought_hindi_style,
                )
            )
        story.append(
            _make_paragraph(
                content,
                body_style,
                devanagari=transcript_hindi_style,
                allow_breaks=True,
            )
        )
        story.append(Spacer(1, 6))

    doc.build(story)
    buf.seek(0)
    filename = f"Program_Counsellor_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/")
async def root() -> Dict[str, str]:
    return {"message": "AI Negotiation Arena API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

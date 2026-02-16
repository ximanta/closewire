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
import random
import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from typing_extensions import TypedDict

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


DEFAULT_NEGOTIATION_MAX_ROUNDS = _env_int("NEGOTIATION_MAX_ROUNDS", 10, 1, 50)
NEGOTIATION_MAX_ROUNDS_LIMIT = _env_int("NEGOTIATION_MAX_ROUNDS_LIMIT", 20, 1, 100)
AUTH_TOKEN_TTL_SECONDS = _env_int("AUTH_TOKEN_TTL_SECONDS", 43200, 60, 604800)

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
    negotiation_model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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


class PersonaProfile(TypedDict):
    name: str
    background: str
    career_stage: str
    persona_type: str
    financial_sensitivity: str
    risk_tolerance: str
    emotional_tone: str
    primary_objections: List[str]
    walk_away_likelihood: float
    expected_roi_months: int
    affordability_concern_level: int
    willingness_to_invest_score: int


class AnalyzeUrlRequest(BaseModel):
    url: HttpUrl
    auth_token: str


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int


class AnalyzeUrlResponse(BaseModel):
    session_id: str
    program: Dict[str, Any]
    persona: Dict[str, Any]
    source: str


class NegotiationConfig(BaseModel):
    session_id: str
    auth_token: str
    demo_mode: bool = True
    retry_mode: bool = False


class ReportRequest(BaseModel):
    session_id: str
    auth_token: str
    transcript: List[Dict[str, Any]]
    analysis: Dict[str, Any]


class NegotiationState(TypedDict):
    round: int
    max_rounds: int
    messages: List[Dict[str, Any]]
    counsellor_position: Dict[str, Any]
    student_position: Dict[str, Any]
    program: ProgramSummary
    persona: PersonaProfile
    deal_status: str
    negotiation_metrics: Dict[str, Any]
    retry_context: Dict[str, Any]


SESSION_STORE: Dict[str, Dict[str, Any]] = {}
AUTH_TOKENS: Dict[str, float] = {}
AUTH_FILE = Path(__file__).with_name("auth.json")

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
    raw = text or ""
    currency_matches = re.findall(
        r"(?:\u20b9|inr|rs\.?)\s*([0-9][0-9,]{3,9})",
        raw,
        flags=re.IGNORECASE,
    )
    if currency_matches:
        values = [int(v.replace(",", "")) for v in currency_matches]
        return max(1000, max(values))

    generic_matches = re.findall(r"\b([0-9][0-9,]{3,9})\b", raw)
    if generic_matches:
        values = [int(v.replace(",", "")) for v in generic_matches]
        return max(1000, max(values))
    return 4500


def _extract_offer_amount(text: str) -> Optional[int]:
    raw = text or ""
    inr_match = re.findall(
        r"(?:\u20b9|inr|rs\.?)\s*([0-9][0-9,]{2,9})",
        raw,
        flags=re.IGNORECASE,
    )
    if inr_match:
        return int(inr_match[-1].replace(",", ""))

    usd_match = re.findall(r"\$([0-9][0-9,]{2,9})", raw)
    if usd_match:
        return int(usd_match[-1].replace(",", ""))
    return None


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
    Scrapes text from a URL, stripping non-content tags.
    """
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "svg", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        return sanitize_text(text)
    except Exception as exc:
        return f"Error extracting from URL: {str(exc)}"


def _extract_response_fields(text: str) -> Dict[str, Any]:
    raw = text or ""
    message = ""
    intent = ""
    techniques: List[str] = []
    confidence = 60
    emotional_state = "calm"

    message_match = re.search(
        r"MESSAGE:\s*(.*?)(?:\n(?:TECHNIQUES_USED|STRATEGIC_INTENT|CONFIDENCE_SCORE|EMOTIONAL_STATE)\s*:|$)",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if message_match:
        message = message_match.group(1).strip()

    techniques_match = re.search(r"TECHNIQUES_USED:\s*\[(.*?)\]", raw, flags=re.IGNORECASE | re.DOTALL)
    if techniques_match:
        techniques = [
            item.strip().strip('"').strip("'")
            for item in techniques_match.group(1).split(",")
            if item.strip()
        ]

    intent_match = re.search(r"STRATEGIC_INTENT:\s*(.*)", raw, flags=re.IGNORECASE)
    if intent_match:
        intent = intent_match.group(1).strip()

    confidence_match = re.search(r"CONFIDENCE_SCORE:\s*([0-9]+(?:\.[0-9]+)?)", raw, flags=re.IGNORECASE)
    if confidence_match:
        try:
            confidence = int(float(confidence_match.group(1)))
        except Exception:
            confidence = 60

    emotional_match = re.search(r"EMOTIONAL_STATE:\s*([a-zA-Z_ -]+)", raw, flags=re.IGNORECASE)
    if emotional_match:
        emotional_state = emotional_match.group(1).strip().lower()

    if not message:
        message = raw.strip()

    message = re.sub(r"\s+\n", "\n", message).strip()
    return {
        "message": message,
        "techniques": techniques,
        "intent": intent,
        "confidence_score": max(0, min(100, confidence)),
        "emotional_state": emotional_state,
    }


def _trim_messages(messages: List[Dict[str, Any]], max_messages: int = 12) -> List[Dict[str, Any]]:
    return messages[-max_messages:]


def _analyze_program(url: str) -> Tuple[ProgramSummary, str]:
    client, negotiation_model_name, _ = get_client_and_models()
    source = "url_content"
    clean_text = extract_from_url(url)[:25000]
    if clean_text.startswith("Error extracting from URL:"):
        source = "fallback"
    fallback = {
        "program_name": "Unknown Program",
        "value_proposition": "Career outcomes through practical learning.",
        "key_features": ["Structured curriculum", "Industry relevance"],
        "target_audience": "Early and mid-career professionals",
        "positioning_angle": "Outcome-focused upskilling",
        "duration": "Not specified",
        "format": "Not specified",
        "weekly_time_commitment": "Not specified",
        "program_fee_inr": "INR 4,500",
        "placement_support_details": "General career guidance.",
        "certification_details": "Certificate on successful completion.",
        "curriculum_modules": ["Foundations", "Hands-on projects"],
        "learning_outcomes": ["Practical skills", "Career readiness"],
        "cohort_start_dates": [],
        "faqs": [],
        "projects_use_cases": [],
        "program_curriculum_coverage": "Not specified",
        "tools_frameworks_technologies": [],
        "emi_or_financing_options": "Not specified",
    }
    prompt = f"""
Analyze content of this URL for an enrollment counsellor. Extract concrete facts only.
URL: {url}
PAGE_TEXT:
{clean_text}
"""
    parsed = _call_function_json(
        client=client,
        model_name=negotiation_model_name,
        prompt=prompt,
        function_name="set_program_summary",
        function_description="Return structured program positioning details extracted from URL content.",
        parameters_schema={
            "type": "object",
            "properties": {
                "program_name": {"type": "string"},
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


def _generate_persona(program: ProgramSummary) -> PersonaProfile:
    client, negotiation_model_name, _ = get_client_and_models()
    prompt = f"""
Generate a realistic prospective student persona for this course and call the function.
Use one archetype from: cost-conscious, working-professional, confused-explorer, career-switcher, ambitious-builder.
PROGRAM:
{json.dumps(program)}
"""
    fallback: PersonaProfile = {
        "name": random.choice(["Aman", "Riya", "Saurabh", "Neha"]),
        "background": "Prospective learner evaluating a new AI upskilling path.",
        "career_stage": random.choice(["early", "mid"]),
        "persona_type": random.choice(
            ["cost-conscious", "working-professional", "confused-explorer", "career-switcher", "ambitious-builder"]
        ),
        "financial_sensitivity": random.choice(["medium", "high"]),
        "risk_tolerance": random.choice(["low", "medium"]),
        "emotional_tone": random.choice(["calm", "skeptical", "confused"]),
        "primary_objections": ["Program clarity", "Career ROI", "Time commitment", "Fee and discount"],
        "walk_away_likelihood": round(random.uniform(0.2, 0.6), 2),
        "expected_roi_months": random.randint(6, 18),
        "affordability_concern_level": random.randint(35, 85),
        "willingness_to_invest_score": random.randint(35, 75),
    }
    parsed = _call_function_json(
        client=client,
        model_name=negotiation_model_name,
        prompt=prompt,
        function_name="set_student_persona",
        function_description="Return a structured prospective student persona.",
        parameters_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "background": {"type": "string"},
                "career_stage": {"type": "string"},
                "persona_type": {"type": "string"},
                "financial_sensitivity": {"type": "string"},
                "risk_tolerance": {"type": "string"},
                "emotional_tone": {"type": "string"},
                "primary_objections": {"type": "array", "items": {"type": "string"}},
                "walk_away_likelihood": {"type": "number"},
                "expected_roi_months": {"type": "integer"},
                "affordability_concern_level": {"type": "integer"},
                "willingness_to_invest_score": {"type": "integer"},
            },
            "required": [
                "name",
                "background",
                "career_stage",
                "persona_type",
                "financial_sensitivity",
                "risk_tolerance",
                "emotional_tone",
                "primary_objections",
                "walk_away_likelihood",
                "expected_roi_months",
                "affordability_concern_level",
                "willingness_to_invest_score",
            ],
        },
        fallback=fallback,
    )
    parsed = _to_plain_json(parsed)
    parsed["walk_away_likelihood"] = float(max(0.0, min(1.0, float(parsed.get("walk_away_likelihood", 0.4)))))
    parsed["expected_roi_months"] = int(max(1, min(60, int(parsed.get("expected_roi_months", fallback["expected_roi_months"])))))
    parsed["affordability_concern_level"] = int(
        max(0, min(100, int(parsed.get("affordability_concern_level", fallback["affordability_concern_level"])))
    ))
    parsed["willingness_to_invest_score"] = int(
        max(0, min(100, int(parsed.get("willingness_to_invest_score", fallback["willingness_to_invest_score"])))
    ))
    return parsed


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
    return f"""
ROLE: Senior Admissions Counsellor.

PRIMARY OBJECTIVE:
Guide the student toward a confident enrollment decision using only factual program data.

DO NOT:
- Promise guaranteed jobs
- Overstate placement outcomes
- Invent program details

PROGRAM DATA:
{json.dumps(state['program'])}

STUDENT PERSONA:
{json.dumps(state['persona'])}

PRIOR TRANSCRIPT:
{transcript}
{retry_note}

STRATEGY REQUIREMENTS:
- Clarify curriculum and modules.
- Explain workload realistically.
- Address ROI concerns using data.
- Handle discount requests ethically.
- Offer EMI or scholarship framing when plausible.
- Reduce affordability anxiety.
- Build trust gradually.
- Detect emotional state shifts.
- Move toward commitment questions after objections resolved.

ADVANCED RULE:
If primary objection remains unresolved, address it directly before attempting close.

OUTPUT FORMAT:
MESSAGE: <dialogue>
TECHNIQUES_USED: [consultative_selling, objection_reframing, roi_framing, workload_validation, etc]
STRATEGIC_INTENT: <one sentence>
CONFIDENCE_SCORE: <0-100>
MESSAGE must end as a complete sentence, never cut mid-sentence.
"""


def _build_student_prompt(state: NegotiationState) -> str:
    transcript = "\n".join(
        f"{m['agent'].upper()}: {m['content']}" for m in _trim_messages(state["messages"], 12)
    )
    return f"""
ROLE: Prospective Student.

PERSONA:
{json.dumps(state['persona'])}

CONSTRAINTS:
- Willingness to invest score (0-100): {state['persona']['willingness_to_invest_score']}
- Affordability concern level (0-100): {state['persona']['affordability_concern_level']}
- Walk-away likelihood: {state['persona']['walk_away_likelihood']}
- Emotional tone baseline: {state['persona']['emotional_tone']}
- Expected ROI months: {state['persona']['expected_roi_months']}

PROGRAM:
{json.dumps(state['program'])}

CURRENT OFFER FROM COUNSELLOR:
{state['counsellor_position']['current_offer']}

CONTEXT:
{transcript}

Output exactly:
MESSAGE: <dialogue>
EMOTIONAL_STATE: calm/frustrated/confused/excited/skeptical
STRATEGIC_INTENT: <why responding this way>
MESSAGE must be complete and not cut mid-sentence.
"""


async def _stream_agent_response(
    websocket: WebSocket,
    client: genai.Client,
    model_name: str,
    prompt: str,
    agent: str,
    round_number: int,
    message_id: str,
    demo_mode: bool,
) -> Dict[str, Any]:
    full_text = ""
    try:
        config = types.GenerateContentConfig(
            temperature=0.85,
            top_p=0.95,
            max_output_tokens=1200,
        )
        response_stream = client.models.generate_content_stream(
            model=model_name,
            contents=prompt,
            config=config,
        )
        for chunk in response_stream:
            text = getattr(chunk, "text", None)
            if not text:
                continue
            full_text += text
            await _ws_send_json(
                websocket,
                {"type": "stream_chunk", "data": {"agent": agent, "text": text, "message_id": message_id}},
            )
            if demo_mode:
                await asyncio.sleep(0.03)
    except Exception as exc:
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
        try:
            await _ws_send_json(websocket, {"type": "error", "data": {"message": f"{agent} streaming failed"}})
        except ClientStreamClosed:
            logger.info("Skipped error send because websocket already closed")
        raise

    fields = _extract_response_fields(full_text)
    msg = {
        "id": message_id,
        "round": round_number,
        "agent": agent,
        "content": fields["message"],
        "techniques": fields["techniques"],
        "strategic_intent": fields["intent"],
        "confidence_score": fields["confidence_score"],
        "emotional_state": fields["emotional_state"],
        "timestamp": datetime.now().isoformat(),
    }
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

    coun_offer = prev_offer
    candidate = _extract_offer_amount(counsellor_msg["content"])
    if candidate is not None:
        floor = state["counsellor_position"]["floor_offer"]
        if floor <= candidate <= prev_offer:
            coun_offer = candidate

    stu_offer = prev_student_offer
    candidate = _extract_offer_amount(student_msg["content"])
    if candidate is not None:
        if 0 < candidate <= state["student_position"]["budget"]:
            stu_offer = candidate

    if coun_offer < prev_offer:
        metrics["concession_count_counsellor"] += 1
    if stu_offer > prev_student_offer:
        metrics["concession_count_student"] += 1

    state["counsellor_position"]["current_offer"] = coun_offer
    state["student_position"]["current_offer"] = stu_offer

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
    prompt = f"""
You are an expert admissions audit evaluator.

Analyze the full enrollment counselling transcript.

Determine:
1. Commitment signal level:
   - none
   - soft_commitment
   - conditional_commitment
   - strong_commitment
2. Enrollment likelihood (0-100)
3. Primary unresolved objection
4. Trust delta (-20 to +20)
5. Who won:
   - counsellor (student likely to enroll)
   - student (not convinced)
   - no-deal

Do NOT evaluate based on price convergence alone.
Focus on emotional trajectory and objection handling.

Be realistic and critical.
Return structured function output only.

Call the function with the final structured verdict.
METRICS:
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
                "negotiation_score": {"type": "number"},
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
                "negotiation_score",
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
            "negotiation_score": 0,
            "skill_recommendations": [],
        },
    )
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
    program, source = _analyze_program(url)
    program = _to_plain_json(program)
    persona = _generate_persona(program)
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

        persona = session["persona"]
        program = session["program"]
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
            "program": program,
            "persona": persona,
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

        while state["round"] <= state["max_rounds"] and state["deal_status"] == "ongoing":
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
            )
            state["messages"].append(counsellor_msg)

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
            )
            state["messages"].append(student_msg)

            _update_metrics(state, counsellor_msg, student_msg)
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
                    },
                },
            )
            await _ws_send_json(websocket, {"type": "metrics_update", "data": state["negotiation_metrics"]})

            state["round"] += 1
            if config.demo_mode:
                await asyncio.sleep(0.6)

        analysis = await _judge_outcome(state)
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
            "analysis": analysis,
            "deal_status": state["deal_status"],
        }
        logger.info("Session %s finished with %s", config.session_id, state["deal_status"])
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except ClientStreamClosed:
        logger.info("Negotiation stopped because client disconnected")
    except Exception as exc:
        logger.exception("Negotiation failed")
        try:
            await _ws_send_json(websocket, {"type": "error", "data": {"message": str(exc)}})
        except ClientStreamClosed:
            logger.info("Skipped error send because websocket already closed")


@app.post("/generate-report")
async def generate_report(payload: ReportRequest) -> StreamingResponse:
    _require_auth_token(payload.auth_token)
    session = SESSION_STORE.get(payload.session_id, {})
    program = session.get("program", {})
    persona = session.get("persona", {})

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

    judge = payload.analysis or {}
    winner = str(judge.get("winner", "no-deal"))
    commitment = str(judge.get("commitment_signal", "none"))
    commitment_map = {
        "none": "No Commitment",
        "soft_commitment": "Exploring Enrollment",
        "conditional_commitment": "Conditional Yes",
        "strong_commitment": "Confirmed Enrollment",
    }

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#0B1A37"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubTitle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4A638F"),
        spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#1D4A8C"),
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor("#1C2F52"),
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=styles["BodyText"],
        fontSize=8.8,
        leading=12,
        textColor=colors.HexColor("#4B6087"),
    )

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
        story.append(Paragraph(title, section_style))
        if not items:
            story.append(Paragraph(fallback_text, body_style))
            story.append(Spacer(1, 6))
            return
        for item in items:
            story.append(Paragraph(f"- {str(item)}", body_style))
        story.append(Spacer(1, 6))

    story.append(Paragraph("Program Counsellor Report", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))

    summary_rows = [
        ["Outcome", winner],
        ["Final Score", f"{judge.get('negotiation_score', 0)} / 100"],
        ["Commitment Signal", commitment_map.get(commitment, commitment)],
        ["Enrollment Likelihood", f"{judge.get('enrollment_likelihood', 0)}%"],
        ["Trust Delta", str(judge.get("trust_delta", 0))],
    ]
    story.append(Paragraph("Outcome Summary", section_style))
    story.append(card_table(summary_rows, [130, 390]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(str(judge.get("why", "No summary available.")), body_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Persona and Context", section_style))
    persona_rows = [
        ["Student", str(persona.get("name", "Unknown"))],
        ["Persona Type", str(persona.get("persona_type", "n/a"))],
        ["Career Stage", str(persona.get("career_stage", "n/a"))],
        ["Risk Tolerance", str(persona.get("risk_tolerance", "n/a"))],
        ["Program", str(program.get("program_name", "Unknown"))],
    ]
    story.append(card_table(persona_rows, [130, 390]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Primary Unresolved Objection", section_style))
    story.append(Paragraph(str(judge.get("primary_unresolved_objection", "Not specified")), body_style))
    story.append(Spacer(1, 8))

    run_history = payload.analysis.get("run_history", []) if isinstance(payload.analysis, dict) else []
    if isinstance(run_history, list) and len(run_history) > 1:
        story.append(Paragraph("Performance Progression", section_style))
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
    story.append(Paragraph("Conversation Metrics Timeline", section_style))
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
        story.append(Paragraph("No metric events captured.", body_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Transcript", section_style))
    for msg in payload.transcript:
        agent = str(msg.get("agent", "")).upper() or "UNKNOWN"
        rnd = msg.get("round", "-")
        content = str(msg.get("content", "")).replace("\n", "<br/>")
        story.append(Paragraph(f"Round {rnd} - {agent}", meta_style))
        story.append(Paragraph(content, body_style))
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

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from backend.rag.ingest import ingest_trace_payload
except ImportError:
    from rag.ingest import ingest_trace_payload

TRACE_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "outputs" / "tracebility" / "rag"


def _pipeline_trace_dir(mode: str) -> Path:
    normalized = str(mode or "ai_vs_ai").strip().lower()
    if normalized not in {"ai_vs_ai", "human_vs_ai", "agent_powered_human_vs_ai"}:
        normalized = "ai_vs_ai"
    return TRACE_OUTPUT_ROOT / normalized


def _write_human_readable_log(
    session_id: str,
    mode: str,
    trace_payload: Dict[str, Any],
    inserted_count: int,
    inserted_nuggets: List[Dict[str, Any]],
    error: Optional[str] = None,
) -> Path:
    out_dir = _pipeline_trace_dir(mode)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"session_{session_id}_human_readable.log"

    analysis = trace_payload.get("analysis", {}) or {}
    persona = trace_payload.get("persona", {}) or {}
    program = trace_payload.get("program", {}) or {}
    metrics = trace_payload.get("negotiation_metrics", {}) or {}

    lines: List[str] = []
    lines.append(f"CloseWire Session Summary - {datetime.now().isoformat()}")
    lines.append("=" * 72)
    lines.append(f"Session ID: {session_id}")
    lines.append(f"Pipeline: {mode}")
    lines.append(f"Program: {program.get('program_name', 'Unknown')}")
    lines.append(f"Prospect: {persona.get('name', 'Unknown')} ({persona.get('archetype_label', persona.get('archetype_id', 'unknown'))})")
    lines.append(f"Result: {trace_payload.get('deal_status', 'unknown')}")
    lines.append(f"Winner: {analysis.get('winner', 'unknown')}")
    lines.append(f"Commitment Signal: {analysis.get('commitment_signal', 'none')}")
    lines.append(f"Enrollment Probability: {analysis.get('enrollment_likelihood', 0)}")
    lines.append(f"Final Trust Index: {metrics.get('trust_index', 'n/a')}")
    lines.append(f"Final Close Probability: {metrics.get('close_probability', 'n/a')}")
    lines.append("")
    if error:
        lines.append(f"Post-session ingestion status: FAILED - {error}")
    else:
        lines.append(f"Post-session ingestion status: SUCCESS ({inserted_count} nuggets inserted)")
    lines.append("")
    lines.append("Winning Nuggets")
    lines.append("-" * 72)
    if not inserted_nuggets:
        lines.append("No winning triads met the threshold.")
    else:
        for idx, nugget in enumerate(inserted_nuggets, start=1):
            lines.append(f"{idx}. Round {nugget.get('round', 'n/a')} | Technique: {nugget.get('technique', 'n/a')}")
            lines.append(f"   Trigger : {nugget.get('trigger', '')}")
            lines.append(f"   Response: {nugget.get('response', '')}")
            lines.append(
                f"   Outcome : trust_delta={nugget.get('trust_delta', 0)}, skepticism_delta={nugget.get('skepticism_delta', 0)}"
            )
            lines.append("")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


async def run_post_session_jobs(
    session_id: str,
    mode: str,
    trace_payload: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        inserted_count, inserted_nuggets = await ingest_trace_payload(trace_payload, source_name=f"{mode}.json")
        out_file = _write_human_readable_log(
            session_id=session_id,
            mode=mode,
            trace_payload=trace_payload,
            inserted_count=inserted_count,
            inserted_nuggets=inserted_nuggets,
        )
        return {"ok": True, "inserted_count": inserted_count, "log_file": str(out_file)}
    except Exception as exc:
        out_file = _write_human_readable_log(
            session_id=session_id,
            mode=mode,
            trace_payload=trace_payload,
            inserted_count=0,
            inserted_nuggets=[],
            error=str(exc),
        )
        return {"ok": False, "inserted_count": 0, "log_file": str(out_file), "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run post-session jobs from a traceability JSON file.")
    parser.add_argument("--file", required=True, help="Path to conversation_traceability.json")
    parser.add_argument("--mode", required=True, help="Pipeline mode: ai_vs_ai|human_vs_ai|agent_powered_human_vs_ai")
    parser.add_argument("--session-id", required=True, help="Session ID")
    args = parser.parse_args()

    trace_payload = json.loads(Path(args.file).read_text(encoding="utf-8"))

    async def _runner() -> None:
        result = await run_post_session_jobs(args.session_id, args.mode, trace_payload)
        print(json.dumps(result, indent=2))

    asyncio.run(_runner())


if __name__ == "__main__":
    main()

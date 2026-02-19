# CloseWire — The Architecture for the Cognitive Enterprise

CloseWire is a domain-agnostic infrastructure where every conversation is simulated, calibrated, and augmented by AI. We understand that humans learn best in focused environments, and engineering leveraging Gen AI solves the "Simulation Barrier."

## The Vision
Today, you see this applied to **Program Counselling**. But the architecture is domain-agnostic:
- **Enterprise Sales Simulator**: Persona = 'Procurement Manager', Product = 'SaaS Software'.
- **Recruitment & Salary Negotiation Simulator**: Persona = 'Top Tier Candidate', Agent = 'HR Manager'.

At the heart of the platform are three interconnected pipelines that create a continuous flywheel of intelligence.

## The Three Pipelines

### Pipeline 1: The Lab (AI Agent vs. Agent Simulation)
The engine that generates wisdom.
- **Stress Testing**: Run thousands of simulations overnight to see where deals break.
- **Synthetic Gold**: Generates massive data without burning human time.
- **Strategic Observation**: A baseline for "what good looks like."

### Pipeline 2: The Gym (Human vs. Agent)
The CloseWire engine that builds skill.
- **Shadow Observer**: Analyzes tone, detects techniques, and measures 'Trust Deltas' in real-time.
- **Safe Failure**: Trainers can fail safely and receive immediate, metric-driven feedback.

### Pipeline 3: The Arena (Agent-Powered Human vs. AI)
The Copilot pipeline designed for **live** calls.
- **Whispering Coach**: Analyzes objections instantly and retrieves best-performing responses.
- **Real-Time RAG**: Performs Vector Search against **Institutional Memory** to pull statistically proven tactics.

---

## The Global Brain (The "Data Flywheel")
Most training systems have amnesia; CloseWire has **Institutional Memory**.

1. **The Harvester**: Automatically "harvests" successful triads (Objection → Response → Reaction).
2. **The Knowledge Nugget**: Specific winning moves are vectorized and stored in a Vector Database.
3. **The Feedback Loop**: Agents (AI or Human) retrieve these winning moves when facing similar resistance.

The result: Humans and AI co-evolve to achieve measurable quality benchmarks.

---

## Technical Overview

### Backend (`backend/main.py`)
- `FastAPI` + `WebSocket`
- `google-genai` SDK (Gemini)
- `pgvector` for Institutional Memory
- Multi-mode engine: `ai_vs_ai`, `human_vs_ai`, `agent_powered_human_vs_ai`

### Frontend (`frontend/src/App.jsx`)
- Single-page cinematic experience
- Real-time metric visualization (Trust, Tension, Win Probability)
- Copilot/Whispering Coach UI for live assistance

---

## Setup & Prerequisites

### Prerequisites
- Python 3.10+
- Node.js 16+
- Gemini API key
- PostgreSQL with `pgvector` (for the Flywheel)

### Backend
```bash
cd backend
python3 -m pip install -r requirements.txt
```

Create `backend/.env`:
```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
RAG_PIPELINE_ENABLED=true
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/closewire_db
```

### Frontend
```bash
cd frontend
npm install
npm start
```

---

## Troubleshooting
- **RAG/Flywheel issues**: Ensure `pgvector` is installed in your Postgres instance.
- **Auth/Session**: In-memory tokens; restarts clear active sessions.
- **Output blocked**: Check backend logs for Gemini safety filters.



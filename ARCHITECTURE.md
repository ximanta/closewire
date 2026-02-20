# System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLOSEWIRE INFRASTRUCTURE                    │
│                 Architecture for the Cognitive Enterprise           │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (React)                           │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐   │
│  │  Configuration  │  │  Negotiation     │  │    Analysis     │   │
│  │     Panel       │─▶│     Arena        │─▶│   Dashboard     │   │
│  │                 │  │                  │  │                 │   │
│  │ • Upload PDF    │  │ • Live Messages  │  │ • Techniques    │   │
│  │ • Set Personas  │  │ • Price Tracking │  │ • Learning Pts  │   │
│  │ • Config Params │  │ • Technique Tags │  │ • Scoring       │   │
│  └─────────────────┘  └──────────────────┘  └─────────────────┘   │
│           │                     ▲                      ▲            │
│           │                     │                      │            │
│           └─────────────────────┴──────────────────────┘            │
│                          WebSocket (Real-Time)                      │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    │ ws://localhost:8000/negotiate
                                    │
┌───────────────────────────────────┴─────────────────────────────────┐
│                      BACKEND (Python + FastAPI)                      │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │                   Agent Workflow                        │     │
│  │                                                              │     │
│  │    ┌──────────┐      ┌──────────┐      ┌──────────┐       │     │
│  │    │  Sales   │◄────▶│ Customer │◄────▶│  Judge   │       │     │
│  │    │  Agent   │      │  Agent   │      │  Agent   │       │     │
│  │    └──────────┘      └──────────┘      └──────────┘       │     │
│  │         │                  │                  │             │     │
│  │         │                  │                  │             │     │
│  │         └──────────────────┴──────────────────┘             │     │
│  │                            │                                │     │
│  │                    ┌───────▼────────┐                      │     │
│  │                    │  Shared State  │                      │     │
│  │                    │   (TypedDict)  │                      │     │
│  │                    │                │                      │     │
│  │                    │ • Messages     │                      │     │
│  │                    │ • Positions    │                      │     │
│  │                    │ • Techniques   │                      │     │
│  │                    │ • Deal Status  │                      │     │
│  │                    └────────────────┘                      │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │                    Supporting Systems                       │     │
│  │                                                              │     │
│  │  ┌───────────────┐  ┌──────────────┐  ┌───────────────┐  │     │
│  │  │ PDF Processor │  │   WebSocket  │  │  Technique    │  │     │
│  │  │               │  │   Manager    │  │  Analyzer     │  │     │
│  │  │ Extract text  │  │              │  │               │  │     │
│  │  │ from brochures│  │ Real-time    │  │ Pattern       │  │     │
│  │  │               │  │ streaming    │  │ matching      │  │     │
│  │  └───────────────┘  └──────────────┘  └───────────────┘  │     │
│  └────────────────────────────────────────────────────────────┘     │
│                                                                       │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    │ HTTP REST API
                                    │
┌───────────────────────────────────▼─────────────────────────────────┐
│                      GOOGLE GEMINI API                            │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  • Model: gemini-2.5-flash / gemini-2.0-flash                     │
│  • Features: Real-time streaming, Function calling                │
│  • Role: Core reasoning for all primary agents                    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│                      FLYWHEEL (Postgres + pgvector)               │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  • Harvester: Extracts winning triads (Objection/Response/Result) │
│  • Vector Store: Stores "Knowledge Nuggets"                       │
│  • Retrieval: Context-aware advice for "The Arena" (Copilot)      │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════════

                    THE THREE PIELINES DATA FLOW

1. PIPELINE 1: THE LAB (AI vs. AI)
   └─▶ Thousands of autonomous simulations overnight
   └─▶ Discovers winning strategies & generates synthetic training data

2. PIPELINE 2: THE GYM (Human vs. AI)
   └─▶ Human trainee practices against adaptive AI personas
   └─▶ Shadow Observer tracks metrics & provides metric-driven feedback

3. PIPELINE 3: THE ARENA (Agent-Powered Human vs. AI)
   └─▶ Real-time Co-pilot assist during live human-AI interactions
   └─▶ Whispering Coach retrieves statistical "winners" from Flywheel

═══════════════════════════════════════════════════════════════════════

                        AGENT CAPABILITIES

┌─────────────────────────────────────────────────────────────────────┐
│                          SALES AGENT                                 │
├─────────────────────────────────────────────────────────────────────┤
│ Knowledge:                                                           │
│ • Product brochure (web link)                                   │
│ • Target/minimum prices                                             │
│ • NIIT value propositions                                           │
│                                                                      │
│ Techniques:                                                          │
│ • Value-based selling         • Social proof                        │
│ • Anchoring                   • Reciprocity                         │
│ • Urgency creation            • Loss aversion                       │
│ • Authority positioning                                             │
│                                                                      │
│ Strategy:                                                            │
│ • Opens strong at target price                                      │
│ • Makes calculated concessions                                      │
│ • Emphasizes ROI and outcomes                                       │
│ • Adapts to customer responses                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        CUSTOMER AGENT                                │
├─────────────────────────────────────────────────────────────────────┤
│ Personas:                                                            │
│ • EASY: Eager buyer, flexible budget                                │
│ • MODERATE: Thoughtful, needs convincing                            │
│ • TOUGH: Aggressive negotiator, very skeptical                      │
│ • STRATEGIC: Sophisticated, advanced tactics                        │
│                                                                      │
│ Behaviors:                                                           │
│ • Challenges pricing                                                │
│ • Demands proof of value                                            │
│ • References competitors                                            │
│ • Makes strategic counter-offers                                    │
│ • Tests sales agent knowledge                                       │
│                                                                      │
│ Constraints:                                                         │
│ • Budget limit (can stretch 20%)                                    │
│ • Specific requirements                                             │
│ • Willing to walk away                                              │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                          JUDGE AGENT                                 │
├─────────────────────────────────────────────────────────────────────┤
│ Analysis Areas:                                                      │
│ • Outcome assessment (deal/no-deal)                                 │
│ • Technique effectiveness scoring                                   │
│ • Key moment identification                                         │
│ • Learning point extraction                                         │
│ • Objective performance rating                                      │
│                                                                      │
│ Output:                                                              │
│ • Comprehensive written analysis                                    │
│ • Top 3 successes                                                   │
│ • Top 3 improvements needed                                         │
│ • Specific coaching advice                                          │
│ • Overall negotiation score (1-100)                                 │
│                                                                      │
│ Key Feature:                                                         │
│ • UNBIASED - judges both sides objectively                          │
└─────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════

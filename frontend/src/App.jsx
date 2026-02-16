import React, { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const BACKEND_URL = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/negotiate";

const ACTIVATION_STEPS = [
  "Preparing AI Counselling Arena...",
  "Analyzing Program Structure...",
  "Generating Student Persona...",
  "Configuring Negotiation Table...",
];

function App() {
  const [programUrl, setProgramUrl] = useState("https://www.niit.com/india/building-agentic-ai-systems/");
  const [sessionId, setSessionId] = useState("");
  const [stage, setStage] = useState("idle");
  const [program, setProgram] = useState(null);
  const [persona, setPersona] = useState(null);
  const [messages, setMessages] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [metrics, setMetrics] = useState(null);
  const [stateUpdate, setStateUpdate] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [runHistory, setRunHistory] = useState([]);
  const [counsellorName, setCounsellorName] = useState("");
  const [initialOffers, setInitialOffers] = useState({ counsellor_offer: 0, student_offer: 0 });
  const [activationIndex, setActivationIndex] = useState(0);
  const [metricToasts, setMetricToasts] = useState([]);
  const [uiToasts, setUiToasts] = useState([]);
  const [showRestartPulse, setShowRestartPulse] = useState(false);
  const [authToken, setAuthToken] = useState("");
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [passwordInput, setPasswordInput] = useState("");
  const [authError, setAuthError] = useState("");
  const [pendingStart, setPendingStart] = useState(false);

  const wsRef = useRef(null);
  const projectionRef = useRef(null);
  const prevMetricsRef = useRef(null);
  const toastTimerRef = useRef({});
  const uiToastTimerRef = useRef({});

  const offers = useMemo(() => {
    const counsellor = stateUpdate?.counsellor_offer ?? initialOffers.counsellor_offer ?? 0;
    const student = stateUpdate?.student_offer ?? initialOffers.student_offer ?? 0;
    return { counsellor, student };
  }, [stateUpdate, initialOffers]);

  const orderedDrafts = useMemo(() => Object.values(drafts), [drafts]);
  const allCards = useMemo(
    () => [...messages, ...orderedDrafts.map((d) => ({ agent: d.agent, content: d.text, draft: true, id: d.id }))],
    [messages, orderedDrafts]
  );

  const momentumValue = useMemo(() => {
    const closeProbability = metrics?.close_probability ?? 50;
    return Math.max(0, Math.min(100, closeProbability));
  }, [metrics]);

  const momentumLabel = useMemo(() => {
    if (momentumValue >= 70) return "Counsellor momentum";
    if (momentumValue <= 35) return "Student resistance";
    return "Balanced momentum";
  }, [momentumValue]);
  const maxRounds = stateUpdate?.max_rounds || metrics?.max_rounds || 10;

  const bgUrl = `${process.env.PUBLIC_URL || ""}/negotiation.png`;

  const generateCounsellorName = () => {
    const firstNames = ["Preetam", "Riya", "Arjun", "Neha", "Aman", "Karan", "Sana", "Vikram"];
    const lastInitials = ["K", "P", "S", "M", "R", "D", "T", "N"];
    const first = firstNames[Math.floor(Math.random() * firstNames.length)];
    const last = lastInitials[Math.floor(Math.random() * lastInitials.length)];
    return `${first} ${last}`;
  };

  const formatOffer = (value) => `INR ${Number(value || 0).toLocaleString("en-IN")}`;

  const pushUiToast = (text, tone = "negative", timeoutMs = 2800) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setUiToasts((current) => [...current, { id, text, tone }].slice(-4));
    uiToastTimerRef.current[id] = setTimeout(() => {
      setUiToasts((current) => current.filter((item) => item.id !== id));
      delete uiToastTimerRef.current[id];
    }, timeoutMs);
  };

  const resetRun = () => {
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    setMessages([]);
    setDrafts({});
    setMetrics(null);
    setStateUpdate(null);
    setAnalysis(null);
    setMetricToasts([]);
    setActivationIndex(0);
    setInitialOffers({ counsellor_offer: 0, student_offer: 0 });
    prevMetricsRef.current = null;
    setShowRestartPulse(false);
  };

  useEffect(
    () => () => {
      Object.values(uiToastTimerRef.current).forEach((timer) => clearTimeout(timer));
      Object.values(toastTimerRef.current).forEach((timer) => clearTimeout(timer));
    },
    []
  );

  useEffect(() => {
    if (stage !== "analyzing") return undefined;
    const interval = setInterval(() => {
      setActivationIndex((prev) => (prev + 1) % ACTIVATION_STEPS.length);
    }, 420);
    return () => clearInterval(interval);
  }, [stage]);

  useEffect(() => {
    if (!metrics) return;
    const prev = prevMetricsRef.current;
    prevMetricsRef.current = metrics;
    if (!prev) return;

    const nextToasts = [];
    const trustDelta = (metrics.trust_index ?? 0) - (prev.trust_index ?? 0);
    const resistanceDelta = (metrics.objection_intensity ?? 0) - (prev.objection_intensity ?? 0);
    const closeDelta = (metrics.close_probability ?? 0) - (prev.close_probability ?? 0);

    if (trustDelta !== 0) {
      nextToasts.push({
        id: `${Date.now()}-trust`,
        tone: trustDelta > 0 ? "positive" : "negative",
        text: `${trustDelta > 0 ? "+" : ""}${trustDelta} Trust`,
      });
    }
    if (resistanceDelta !== 0) {
      nextToasts.push({
        id: `${Date.now()}-resistance`,
        tone: resistanceDelta < 0 ? "positive" : "negative",
        text: `${resistanceDelta > 0 ? "+" : ""}${resistanceDelta} Resistance`,
      });
    }
    if (Math.abs(closeDelta) >= 4) {
      nextToasts.push({
        id: `${Date.now()}-close`,
        tone: "strategic",
        text: `${closeDelta > 0 ? "+" : ""}${closeDelta} Close Prob`,
      });
    }

    if (!nextToasts.length) return;
    setMetricToasts((current) => [...current, ...nextToasts].slice(-6));
    nextToasts.forEach((toast) => {
      if (toastTimerRef.current[toast.id]) clearTimeout(toastTimerRef.current[toast.id]);
      toastTimerRef.current[toast.id] = setTimeout(() => {
        setMetricToasts((current) => current.filter((item) => item.id !== toast.id));
        delete toastTimerRef.current[toast.id];
      }, 1500);
    });
  }, [metrics]);

  useEffect(() => {
    if (stage === "completed") setShowRestartPulse(true);
  }, [stage]);

  useEffect(() => {
    if (stage !== "negotiating" && stage !== "completed") return;
    const lane = projectionRef.current;
    if (!lane) return;
    lane.scrollTo({ top: lane.scrollHeight, behavior: "smooth" });
  }, [allCards, stage]);

  const startNegotiation = async () => {
    if (!authToken) {
      setShowAuthModal(true);
      setAuthError("");
      setPendingStart(true);
      return;
    }
    await beginNegotiation(authToken);
  };

  const beginNegotiation = async (tokenOverride) => {
    const token = tokenOverride || authToken;
    if (!programUrl.trim()) {
      pushUiToast("Enter a valid program URL to continue.", "strategic");
      return;
    }
    setRunHistory([]);
    resetRun();
    setStage("analyzing");

    try {
      const analyzeRes = await fetch(`${BACKEND_URL}/analyze-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: programUrl.trim(), auth_token: token }),
      });
      if (analyzeRes.status === 401) {
        setAuthToken("");
        setShowAuthModal(true);
        setAuthError("Session expired. Enter password again.");
        setStage("idle");
        return;
      }
      if (!analyzeRes.ok) throw new Error("URL analysis failed");

      const analyzeData = await analyzeRes.json();
      setSessionId(analyzeData.session_id);
      setProgram(analyzeData.program);
      setPersona(analyzeData.persona);
      setCounsellorName(generateCounsellorName());
      setStage("negotiating");
      startWebsocketNegotiation(analyzeData.session_id, token, false);
    } catch (error) {
      pushUiToast(error.message || "Failed to start negotiation");
      setStage("idle");
    }
  };

  const startWebsocketNegotiation = (targetSessionId, token, retryMode = false) => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          session_id: targetSessionId,
          auth_token: token,
          demo_mode: true,
          retry_mode: retryMode,
        })
      );
    };

    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "stream_chunk") {
        const data = payload.data;
        setDrafts((prev) => {
          const current = prev[data.message_id] || { id: data.message_id, agent: data.agent, text: "" };
          return { ...prev, [data.message_id]: { ...current, text: `${current.text}${data.text}` } };
        });
      } else if (payload.type === "message_complete") {
        const msg = payload.data;
        setMessages((prev) => [...prev, msg]);
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[msg.id];
          return next;
        });
      } else if (payload.type === "metrics_update") {
        setMetrics(payload.data);
      } else if (payload.type === "state_update") {
        setStateUpdate(payload.data);
      } else if (payload.type === "session_ready") {
        const data = payload.data || {};
        if (data.initial_offers) {
          setInitialOffers({
            counsellor_offer: data.initial_offers.counsellor_offer ?? 0,
            student_offer: data.initial_offers.student_offer ?? 0,
          });
        }
      } else if (payload.type === "analysis") {
        setAnalysis(payload.data);
        setRunHistory((prev) => [
          ...prev,
          {
            label: retryMode ? `Run ${prev.length + 1} (Retry)` : `Run ${prev.length + 1}`,
            score: payload.data?.judge?.negotiation_score ?? 0,
          },
        ]);
        setStage("completed");
      } else if (payload.type === "error") {
        pushUiToast(payload.data?.message || "Unexpected backend error");
        setStage("idle");
      }
    };

    ws.onerror = () => {
      pushUiToast("WebSocket connection failed. Please retry.");
      setStage("idle");
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      setDrafts({});
      setStage((prev) => (prev === "negotiating" ? "idle" : prev));
    };
  };

  const handlePasswordSubmit = async (event) => {
    event.preventDefault();
    setAuthError("");
    try {
      const response = await fetch(`${BACKEND_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: passwordInput }),
      });
      if (!response.ok) {
        throw new Error("Invalid password");
      }
      const data = await response.json();
      setAuthToken(data.token);
      setShowAuthModal(false);
      setPasswordInput("");
      if (pendingStart) {
        setPendingStart(false);
        await beginNegotiation(data.token);
      }
    } catch (error) {
      setAuthError(error.message || "Authentication failed");
    }
  };

  const startNewSimulation = () => {
    resetRun();
    setRunHistory([]);
    setCounsellorName("");
    setStage("idle");
  };

  const retrySimulation = () => {
    if (!sessionId || !authToken) {
      pushUiToast("Session missing. Start a new simulation.", "strategic");
      return;
    }
    resetRun();
    setStage("negotiating");
    startWebsocketNegotiation(sessionId, authToken, true);
  };

  const downloadReport = async () => {
    if (!sessionId || !analysis) return;
    const res = await fetch(`${BACKEND_URL}/generate-report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        auth_token: authToken,
        transcript: messages,
        analysis: analysis.judge || {},
      }),
    });
    if (!res.ok) {
      pushUiToast("Failed to generate PDF report.");
      return;
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Negotiation_Coaching_Report_${Date.now()}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  };

  return (
    <main className={`app stage-${stage}`} style={{ backgroundImage: `url(${bgUrl})` }}>
      <div className="sceneOverlay" />

      {stage === "idle" && (
        <section className="hero">
          <h1>Negotia</h1>
          <p className="subtitle">Your Personal AI Powered Career Counseler</p>
          <div className="inputRow">
            <input
              type="url"
              value={programUrl}
              onChange={(e) => setProgramUrl(e.target.value)}
              placeholder="Enter Program URL here..."
            />
            <button onClick={startNegotiation}>Start Live Negotiation</button>
          </div>
        </section>
      )}

      <div className="uiToastStack">
        {uiToasts.map((toast) => (
          <div key={toast.id} className={`uiToast ${toast.tone}`}>
            {toast.text}
          </div>
        ))}
      </div>

      {showAuthModal && (
        <div className="authModalBackdrop">
          <form className="authModal" onSubmit={handlePasswordSubmit}>
            <h3>Authentication Required</h3>
            <p>Enter password to start negotiation.</p>
            <input
              type="password"
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              placeholder="Password"
              autoFocus
            />
            {authError && <div className="authError">{authError}</div>}
            <div className="authActions">
              <button type="submit" className="downloadBtn">Unlock</button>
              <button
                type="button"
                className="ghostBtn"
                onClick={() => {
                  setShowAuthModal(false);
                  setPendingStart(false);
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {stage === "analyzing" && (
        <section className="activationOverlay">
          <h2>Arena Activation</h2>
          <div className="activationSteps">
            {ACTIVATION_STEPS.map((step, index) => (
              <p key={step} className={index <= activationIndex ? "active" : ""}>
                {step}
              </p>
            ))}
          </div>
          <div className="activationLine">
            <div className="activationFill" />
          </div>
        </section>
      )}

      {(stage === "negotiating" || stage === "completed") && (
        <section className={`arenaScene ${stage === "completed" ? "freeze" : ""}`}>
          <div className={`momentumBar ${momentumValue > 80 ? "hot" : ""}`}>
            <div className="momentumTrack">
              <div className="momentumLeft" style={{ width: `${momentumValue}%` }} />
              <div className="momentumRight" style={{ width: `${100 - momentumValue}%` }} />
            </div>
            <div className="momentumMeta">
              <span>{momentumLabel}</span>
              <strong>{momentumValue}%</strong>
            </div>
          </div>

          <div className="agentLayer">
            <article className={`agentIdentity counsellor ${momentumValue > 65 ? "glow" : ""}`}>
              <h3>{counsellorName || "Admissions Counsellor"}</h3>
              <p>{program?.program_name || "Program"}</p>
              <strong>{formatOffer(offers.counsellor)}</strong>
            </article>
            <article className={`agentIdentity student ${momentumValue < 40 ? "glow" : ""}`}>
              <h3>Prospective Student</h3>
              <p>{persona?.name || "Persona"}</p>
              <strong>{formatOffer(offers.student)}</strong>
            </article>
          </div>

          <div className="projectionLane" ref={projectionRef}>
            {allCards.map((msg, idx) => (
              <article key={`${msg.id || idx}`} className={`projectionCard ${msg.agent} ${msg.draft ? "draft" : ""}`}>
                <header>
                  <strong>
                    {msg.agent === "counsellor"
                      ? (counsellorName || "Admissions Counsellor")
                      : (persona?.name || "Prospective Student")}
                  </strong>
                  <span>{msg.round ? `Round ${msg.round}` : "Streaming"}</span>
                </header>
                <p>{msg.content}</p>
                {msg.strategic_intent && (
                  <details>
                    <summary>Strategic Intent</summary>
                    <div>{msg.strategic_intent}</div>
                  </details>
                )}
                {msg.techniques?.length > 0 && (
                  <div className="tags">
                    {msg.techniques.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>

          <div className="popupLayer">
            {metricToasts.map((toast) => (
              <div key={toast.id} className={`metricToast ${toast.tone}`}>
                {toast.text}
              </div>
            ))}
          </div>

          <div className={`metricsRibbon ${(metrics?.close_probability ?? 0) > 80 ? "glow" : ""}`}>
            <span>Round {metrics?.round || 1} / {maxRounds}</span>
            <span>Concessions: {metrics?.concession_count_counsellor ?? 0} - {metrics?.concession_count_student ?? 0}</span>
            <span>Tension: {metrics?.tone_escalation ?? 0}%</span>
            <span>Enrollment Probability: {metrics?.close_probability ?? 0}%</span>
            <span>Sentiment: {metrics?.sentiment_indicator || "neutral"}</span>
          </div>
        </section>
      )}

      {stage === "completed" && analysis && (
        <section className="resultOverlay">
          <div className="resultCard">
            <h2>RESULT: {(analysis?.judge?.winner || analysis?.winner || "no-deal").toUpperCase()}</h2>
            <h3>Final Score: {analysis?.judge?.negotiation_score ?? 0} / 100</h3>
            <p>{analysis?.judge?.why || "Simulation completed."}</p>
            <p>Commitment: <strong>{analysis?.judge?.commitment_signal || "none"}</strong> | Enrollment Likelihood: <strong>{analysis?.judge?.enrollment_likelihood ?? 0}%</strong> | Trust Delta: <strong>{analysis?.judge?.trust_delta ?? 0}</strong></p>
            <div className="resultGrid">
              <article>
                <h4>Key Turning Points</h4>
                <ul>{(analysis?.judge?.pivotal_moments || []).map((x) => <li key={x}>{x}</li>)}</ul>
              </article>
              <article>
                <h4>Strengths</h4>
                <ul>{(analysis?.judge?.strengths || []).map((x) => <li key={x}>{x}</li>)}</ul>
              </article>
              <article>
                <h4>Coaching Insights</h4>
                <ul>{(analysis?.judge?.skill_recommendations || []).map((x) => <li key={x}>{x}</li>)}</ul>
              </article>
            </div>
            {runHistory.length >= 2 && (
              <p>
                {runHistory[0].label} Score: {runHistory[0].score} | {runHistory[1].label} Score: {runHistory[1].score} | Improvement: {runHistory[1].score - runHistory[0].score >= 0 ? "+" : ""}{runHistory[1].score - runHistory[0].score}
              </p>
            )}
            <div className="resultActions">
              <button className="downloadBtn" onClick={downloadReport}>
                Download Coaching Report (PDF)
              </button>
              <button className="downloadBtn" onClick={retrySimulation}>
                Retry Simulation (Improved Strategy)
              </button>
              <button className={`ghostBtn ${showRestartPulse ? "pulse" : ""}`} onClick={startNewSimulation}>
                Start New Simulation
              </button>
            </div>
          </div>
        </section>
      )}
    </main>
  );
}

export default App;

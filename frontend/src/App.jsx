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
const COMMITMENT_LABELS = {
  none: "No Commitment",
  soft_commitment: "Exploring Enrollment",
  conditional_commitment: "Conditional Yes",
  strong_commitment: "Confirmed Enrollment",
};

const PILLAR_ITEM_TRUNCATE = 120;
const STUDENT_CONTROL_PREFIXES = [
  "INTERNAL_THOUGHT:",
  "UPDATED_STATS:",
  "UPDATED_STATE:",
  "EMOTIONAL_STATE:",
  "STRATEGIC_INTENT:",
];

const extractSpokenText = (value) => {
  const raw = String(value || "");
  const xmlMessageMatch = raw.match(/<message>\s*([\s\S]*?)\s*<\/message>/i);
  if (xmlMessageMatch?.[1]?.trim()) {
    return xmlMessageMatch[1].trim();
  }
  const inlineMessageMatch = raw.match(
    /MESSAGE:\s*(.*?)(?:(?:\n|\r|\s)(?:INTERNAL_THOUGHT|UPDATED_STATS|UPDATED_STATE|EMOTIONAL_STATE|STRATEGIC_INTENT|TECHNIQUES_USED|CONFIDENCE_SCORE)\s*:|$)/is
  );
  if (inlineMessageMatch?.[1]?.trim()) {
    return inlineMessageMatch[1].trim();
  }
  const lines = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) return "";
  const spoken = [];
  lines.forEach((line) => {
    const upper = line.toUpperCase();
    if (STUDENT_CONTROL_PREFIXES.some((prefix) => upper.startsWith(prefix))) return;
    if (upper.startsWith("<THOUGHT>") || upper.startsWith("</THOUGHT>")) return;
    if (upper.startsWith("<STATS>") || upper.startsWith("</STATS>")) return;
    if (upper.startsWith("<INTENT>") || upper.startsWith("</INTENT>")) return;
    if (upper.startsWith("<EMOTIONAL_STATE>") || upper.startsWith("</EMOTIONAL_STATE>")) return;
    if (upper.startsWith("<MESSAGE>") || upper.startsWith("</MESSAGE>")) {
      const content = line
        .replace(/<message>/i, "")
        .replace(/<\/message>/i, "")
        .trim();
      if (content) spoken.push(content);
      return;
    }
    if (upper.startsWith("MESSAGE:")) {
      const content = line.slice("MESSAGE:".length).trim();
      if (content) spoken.push(content);
      return;
    }
    spoken.push(line);
  });
  return spoken.join(" ").trim();
};

const toTitleCase = (value) =>
  String(value || "")
    .replace(/[_-]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");

const formatCareerStage = (value) => {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "N/A";
  if (normalized === "early") return "Early Career";
  if (normalized === "mid") return "Mid Career";
  if (normalized === "late") return "Late Career";
  return toTitleCase(normalized);
};

const formatArchetype = (persona) => {
  const label = String(persona?.archetype_label || "").trim();
  if (label) return label;
  const fallback = String(persona?.persona_type || "").trim();
  return fallback ? toTitleCase(fallback) : "Learner Profile";
};

const commitmentFromProbability = (probability) => {
  const momentum = Math.max(0, Math.min(100, Number(probability ?? 0)));
  if (momentum >= 80) return "strong_commitment";
  if (momentum >= 60) return "conditional_commitment";
  if (momentum >= 40) return "soft_commitment";
  return "none";
};

const chipStateClass = (state) => {
  if (state === "danger") return "chip-state-danger";
  if (state === "warning") return "chip-state-warning";
  if (state === "success") return "chip-state-success";
  if (state === "magic") return "chip-state-magic";
  if (state === "muted") return "chip-state-muted";
  return "chip-state-neutral";
};

const commitmentSignalState = (signal) => {
  const normalized = String(signal || "").toLowerCase();
  if (normalized === "strong_commitment") return "magic";
  if (normalized === "conditional_commitment") return "success";
  if (normalized === "soft_commitment") return "warning";
  return "muted";
};

const formatDurationHms = (totalSeconds) => {
  const safe = Math.max(0, Number(totalSeconds || 0));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = Math.floor(safe % 60);
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
};

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
  const [metricEventHistory, setMetricEventHistory] = useState([]);
  const [selectedTimelineRound, setSelectedTimelineRound] = useState(null);
  const [activationIndex, setActivationIndex] = useState(0);
  const [metricToasts, setMetricToasts] = useState([]);
  const [uiToasts, setUiToasts] = useState([]);
  const [showRestartPulse, setShowRestartPulse] = useState(false);
  const [authToken, setAuthToken] = useState("");
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [passwordInput, setPasswordInput] = useState("");
  const [authError, setAuthError] = useState("");
  const [pendingStart, setPendingStart] = useState(false);
  const [expandedContent, setExpandedContent] = useState(null);
  const [showReportDashboard, setShowReportDashboard] = useState(false);
  const [chipFlash, setChipFlash] = useState({});
  const [runDurationSeconds, setRunDurationSeconds] = useState(0);

  const wsRef = useRef(null);
  const projectionRef = useRef(null);
  const prevMetricsRef = useRef(null);
  const toastTimerRef = useRef({});
  const uiToastTimerRef = useRef({});
  const pendingThoughtsRef = useRef({});
  const chipFlashTimerRef = useRef({});
  const runStartEpochRef = useRef(null);

  const orderedDrafts = useMemo(() => Object.values(drafts), [drafts]);
  const allCards = useMemo(
    () => [
      ...messages,
      ...orderedDrafts
        .map((d) => ({
          agent: d.agent,
          content: d.agent === "student" ? extractSpokenText(d.text) : d.text,
          draft: true,
          id: d.id,
        }))
        .filter((card) => String(card.content || "").trim()),
    ],
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
  const liveCommitment = useMemo(() => commitmentFromProbability(momentumValue), [momentumValue]);
  const liveCommitmentLabel = COMMITMENT_LABELS[liveCommitment] || COMMITMENT_LABELS.none;
  const currentRound = metrics?.round ?? stateUpdate?.round ?? 1;
  const trustBaseline = 50 + (metrics?.retry_modifier ?? 0);
  const liveTrustDelta = (metrics?.trust_index ?? trustBaseline) - trustBaseline;
  const maxRounds = stateUpdate?.max_rounds || metrics?.max_rounds || 10;
  const roundEventSummary = useMemo(() => {
    const roundMap = {};
    metricEventHistory.forEach((item) => {
      const key = item.round || 1;
      if (!roundMap[key]) {
        roundMap[key] = [];
      }
      roundMap[key].push(item);
    });
    return Object.entries(roundMap)
      .map(([round, events]) => ({ round: Number(round), events }))
      .sort((left, right) => left.round - right.round);
  }, [metricEventHistory]);
  const retryPerformance = useMemo(() => {
    if (runHistory.length < 2) return null;
    const baseline = runHistory[0]?.score ?? 0;
    const bestScore = Math.max(...runHistory.map((run) => run.score));
    const points = runHistory.map((run, index) => {
      const previous = runHistory[index - 1];
      return {
        ...run,
        runNumber: index + 1,
        deltaFromPrevious: index === 0 ? 0 : run.score - previous.score,
        deltaFromBaseline: run.score - baseline,
        isBest: run.score === bestScore,
      };
    });
    return {
      baseline,
      bestScore,
      points,
      latest: points[points.length - 1],
      previous: points[points.length - 2],
    };
  }, [runHistory]);
  const roundInsights = useMemo(() => {
    const objectionTokens = ["price", "cost", "expensive", "risk", "uncertain", "time", "trust", "proof"];
    return roundEventSummary.map((row) => {
      const roundMessages = messages.filter((m) => m.round === row.round);
      const studentMessages = roundMessages.filter((m) => m.agent === "student");
      const counsellorMessages = roundMessages.filter((m) => m.agent === "counsellor");
      const latestStudent = studentMessages[studentMessages.length - 1];
      const latestCounsellor = counsellorMessages[counsellorMessages.length - 1];
      const studentText = (latestStudent?.content || "").toLowerCase();
      const objectionHits = objectionTokens.reduce((count, token) => count + (studentText.includes(token) ? 1 : 0), 0);
      const trustDelta = row.events
        .filter((event) => event.text.toLowerCase().includes("trust"))
        .reduce((sum, event) => sum + (parseInt(event.text, 10) || 0), 0);
      const closeDelta = row.events
        .filter((event) => event.text.toLowerCase().includes("close"))
        .reduce((sum, event) => sum + (parseInt(event.text, 10) || 0), 0);
      const resistanceDelta = row.events
        .filter((event) => event.text.toLowerCase().includes("resistance"))
        .reduce((sum, event) => sum + (parseInt(event.text, 10) || 0), 0);
      const tacticalMove = latestCounsellor?.strategic_intent
        || (latestCounsellor?.techniques || []).slice(0, 2).join(", ")
        || "Consultative follow-up";
      const compactDelta = row.events
        .slice(0, 3)
        .map((event) => event.text.replace(" Resistance", "R").replace(" Trust", "T").replace(" Close Prob", "CP"))
        .join("  ");
      const metricChips = row.events.slice(0, 3).map((event) => ({
        text: event.text,
        tone: event.tone || "strategic",
      }));
      return {
        round: row.round,
        compactDelta: compactDelta || "No major swing",
        metricChips,
        emotionalShift: latestStudent?.emotional_state || "calm",
        objectionSpike: objectionHits,
        trustDelta,
        resistanceDelta,
        closeDelta,
        tacticalMove,
      };
    });
  }, [messages, roundEventSummary]);
  const activeRoundInsight = useMemo(() => {
    if (!roundInsights.length) return null;
    if (selectedTimelineRound == null) return roundInsights[roundInsights.length - 1];
    return roundInsights.find((item) => item.round === selectedTimelineRound) || roundInsights[roundInsights.length - 1];
  }, [roundInsights, selectedTimelineRound]);
  const roundChipState = useMemo(() => {
    const round = Number(metrics?.round || 1);
    const max = Number(maxRounds || 1);
    if (round >= max) return "danger";
    if (round >= 4) return "warning";
    return "neutral";
  }, [metrics?.round, maxRounds]);
  const concessionsChipState = useMemo(() => {
    const coun = Number(metrics?.concession_count_counsellor || 0);
    const stu = Number(metrics?.concession_count_student || 0);
    if (coun === 0 && stu === 0) return "muted";
    return "neutral";
  }, [metrics?.concession_count_counsellor, metrics?.concession_count_student]);
  const tensionChipState = useMemo(() => {
    const tension = Number(metrics?.tone_escalation || 0);
    if (tension > 65) return "danger";
    if (tension >= 31) return "warning";
    return "success";
  }, [metrics?.tone_escalation]);
  const enrollmentChipState = useMemo(() => {
    const probability = Number(metrics?.close_probability || 0);
    if (probability >= 80) return "magic";
    if (probability >= 60) return "success";
    if (probability >= 36) return "warning";
    return "danger";
  }, [metrics?.close_probability]);
  const commitmentChipState = useMemo(() => {
    if (liveCommitment === "strong_commitment") return "magic";
    if (liveCommitment === "conditional_commitment") return "success";
    if (liveCommitment === "soft_commitment") return "warning";
    return "muted";
  }, [liveCommitment]);
  const trustChipState = useMemo(() => {
    if (liveTrustDelta > 0) return "success";
    if (liveTrustDelta < 0) return "danger";
    return "neutral";
  }, [liveTrustDelta]);
  const sentimentChipState = useMemo(() => {
    const sentiment = String(metrics?.sentiment_indicator || "").toLowerCase();
    if (sentiment.includes("positive") || sentiment.includes("excited")) return "success";
    if (sentiment.includes("negative") || sentiment.includes("frustrated")) return "danger";
    return "warning";
  }, [metrics?.sentiment_indicator]);

  const pulseChip = (key) => {
    setChipFlash((current) => ({ ...current, [key]: true }));
    if (chipFlashTimerRef.current[key]) clearTimeout(chipFlashTimerRef.current[key]);
    chipFlashTimerRef.current[key] = setTimeout(() => {
      setChipFlash((current) => ({ ...current, [key]: false }));
      delete chipFlashTimerRef.current[key];
    }, 1000);
  };

  const renderMetricChips = () => (
    <>
      <span className={`metricChip ${chipStateClass(roundChipState)} ${chipFlash.round ? "animate-flash-update" : ""}`}>
        Round {metrics?.round || 1} / {maxRounds}
      </span>
      <span className={`metricChip ${chipStateClass(concessionsChipState)} ${chipFlash.concessions ? "animate-flash-update" : ""}`}>
        Concessions {metrics?.concession_count_counsellor ?? 0} - {metrics?.concession_count_student ?? 0}
      </span>
      <span className={`metricChip ${chipStateClass(tensionChipState)} ${tensionChipState === "danger" ? "danger-pulse" : ""} ${chipFlash.tension ? "animate-flash-update" : ""}`}>
        Tension {metrics?.tone_escalation ?? 0}%
      </span>
      <span className={`metricChip enrollmentChip ${chipStateClass(enrollmentChipState)} ${chipFlash.enrollment ? "animate-flash-update" : ""}`}>
        Enrollment Probability {metrics?.close_probability ?? 0}%
      </span>
      <span className={`metricChip commitmentChip ${chipStateClass(commitmentChipState)} ${chipFlash.commitment ? "animate-flash-update" : ""}`}>
        <span className="statusDot" />
        {liveCommitmentLabel}
      </span>
      <span className={`metricChip trustChip ${chipStateClass(trustChipState)} ${chipFlash.trust ? "animate-flash-update" : ""}`}>
        Trust Delta {liveTrustDelta >= 0 ? "+" : ""}{liveTrustDelta}
      </span>
      <span className={`metricChip ${chipStateClass(sentimentChipState)} ${chipFlash.sentiment ? "animate-flash-update" : ""}`}>
        Sentiment {metrics?.sentiment_indicator || "neutral"}
      </span>
    </>
  );
  const outcomeHeadline = useMemo(() => {
    const winner = analysis?.judge?.winner || analysis?.winner || "no-deal";
    if (winner === "counsellor") {
      return `${counsellorName || "Counsellor"} Successfully Secured Enrollment`;
    }
    if (winner === "student") {
      return `${persona?.name || "Student"} Was Not Convinced`;
    }
    return "Outcome: No Deal";
  }, [analysis, counsellorName, persona]);

  const bgUrl = `${process.env.PUBLIC_URL || ""}/negotiation.png`;

  const generateCounsellorName = () => {
    const firstNames = ["Preetam", "Riya", "Arjun", "Neha", "Aman", "Karan", "Sana", "Vikram"];
    const lastInitials = ["K", "P", "S", "M", "R", "D", "T", "N"];
    const first = firstNames[Math.floor(Math.random() * firstNames.length)];
    const last = lastInitials[Math.floor(Math.random() * lastInitials.length)];
    return `${first} ${last}`;
  };

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
    setSelectedTimelineRound(null);
    setMetricToasts([]);
    setActivationIndex(0);
    setMetricEventHistory([]);
    setExpandedContent(null);
    pendingThoughtsRef.current = {};
    setShowReportDashboard(false);
    prevMetricsRef.current = null;
    setShowRestartPulse(false);
    setRunDurationSeconds(0);
    runStartEpochRef.current = null;
  };

  useEffect(
    () => () => {
      Object.values(uiToastTimerRef.current).forEach((timer) => clearTimeout(timer));
      Object.values(toastTimerRef.current).forEach((timer) => clearTimeout(timer));
      Object.values(chipFlashTimerRef.current).forEach((timer) => clearTimeout(timer));
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
    if ((metrics.round ?? 1) !== (prev.round ?? 1)) pulseChip("round");
    if (
      (metrics.concession_count_counsellor ?? 0) !== (prev.concession_count_counsellor ?? 0)
      || (metrics.concession_count_student ?? 0) !== (prev.concession_count_student ?? 0)
    ) pulseChip("concessions");
    if ((metrics.tone_escalation ?? 0) !== (prev.tone_escalation ?? 0)) pulseChip("tension");
    if (closeDelta !== 0) pulseChip("enrollment");
    const prevCommitment = commitmentFromProbability(prev.close_probability ?? 50);
    const nextCommitment = commitmentFromProbability(metrics.close_probability ?? 50);
    if (prevCommitment !== nextCommitment) pulseChip("commitment");
    if (trustDelta !== 0) pulseChip("trust");
    if ((metrics.sentiment_indicator || "neutral") !== (prev.sentiment_indicator || "neutral")) pulseChip("sentiment");

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
    setMetricEventHistory((current) => {
      const stamped = nextToasts.map((item) => ({
        id: `${item.id}-h`,
        text: item.text,
        tone: item.tone,
        round: currentRound,
        timestamp: new Date().toISOString(),
      }));
      return [...current, ...stamped].slice(-80);
    });
    nextToasts.forEach((toast) => {
      if (toastTimerRef.current[toast.id]) clearTimeout(toastTimerRef.current[toast.id]);
      toastTimerRef.current[toast.id] = setTimeout(() => {
        setMetricToasts((current) => current.filter((item) => item.id !== toast.id));
        delete toastTimerRef.current[toast.id];
      }, 3200);
    });
  }, [metrics, currentRound]);

  useEffect(() => {
    if (stage === "completed") setShowRestartPulse(true);
  }, [stage]);

  useEffect(() => {
    if (!expandedContent) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onEscape = (event) => {
      if (event.key === "Escape") {
        setExpandedContent(null);
      }
    };
    window.addEventListener("keydown", onEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onEscape);
    };
  }, [expandedContent]);

  useEffect(() => {
    if (stage !== "negotiating" && stage !== "completed") return;
    const lane = projectionRef.current;
    if (!lane) return;
    requestAnimationFrame(() => {
      lane.scrollTop = lane.scrollHeight;
    });
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
      runStartEpochRef.current = Date.now();
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
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        // Keep UI alive and surface malformed payloads in dev tools.
        // eslint-disable-next-line no-console
        console.error("WS payload parse failed", { raw: event.data, error });
        pushUiToast("Malformed server event received.");
        return;
      }
      if (payload.type === "stream_chunk") {
        const data = payload.data;
        setDrafts((prev) => {
          const current = prev[data.message_id] || { id: data.message_id, agent: data.agent, text: "" };
          return { ...prev, [data.message_id]: { ...current, text: `${current.text}${data.text}` } };
        });
      } else if (payload.type === "student_thought") {
        const data = payload.data || {};
        if (data.message_id && data.thought) {
          pendingThoughtsRef.current = { ...pendingThoughtsRef.current, [data.message_id]: data.thought };
        }
      } else if (payload.type === "message_complete") {
        const msg = payload.data;
        const thoughtText = msg.internal_thought || pendingThoughtsRef.current[msg.id] || "";
        const normalized = {
          ...msg,
          content: msg.agent === "student" ? extractSpokenText(msg.content) : msg.content,
          internal_thought: thoughtText,
        };
        setMessages((prev) => [...prev, normalized]);
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[msg.id];
          return next;
        });
        if (pendingThoughtsRef.current[msg.id]) {
          const next = { ...pendingThoughtsRef.current };
          delete next[msg.id];
          pendingThoughtsRef.current = next;
        }
      } else if (payload.type === "metrics_update") {
        setMetrics(payload.data);
      } else if (payload.type === "state_update") {
        setStateUpdate(payload.data);
      } else if (payload.type === "analysis") {
        const endedAt = Date.now();
        const startedAt = runStartEpochRef.current || endedAt;
        const durationSeconds = Math.max(0, Math.floor((endedAt - startedAt) / 1000));
        const durationHms = formatDurationHms(durationSeconds);
        setRunDurationSeconds(durationSeconds);
        setAnalysis({ ...payload.data, duration_seconds: durationSeconds, duration_hms: durationHms });
        setRunHistory((prev) => [
          ...prev,
          {
            label: retryMode ? `Run ${prev.length + 1} (Retry)` : `Run ${prev.length + 1}`,
            score: payload.data?.judge?.negotiation_score ?? 0,
          },
        ]);
        setStage("completed");
        setShowReportDashboard(false);
        pushUiToast(`Conversation Completed\nDuration (mins) ${durationHms}`, "positive", 5200);
      } else if (payload.type === "error") {
        // eslint-disable-next-line no-console
        console.error("Backend negotiation error", payload.data);
        pushUiToast(payload.data?.message || "Unexpected backend error");
      }
    };

    ws.onerror = (event) => {
      // eslint-disable-next-line no-console
      console.error("WebSocket error", event);
      pushUiToast("WebSocket connection failed. Please retry.");
    };

    ws.onclose = (event) => {
      if (wsRef.current !== ws) return;
      // eslint-disable-next-line no-console
      console.warn("WebSocket closed", { code: event.code, reason: event.reason, wasClean: event.wasClean });
      setDrafts({});
      pushUiToast("Connection closed.", "strategic", 1800);
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
    setShowReportDashboard(false);
  };

  const retrySimulation = () => {
    if (!sessionId || !authToken) {
      pushUiToast("Session missing. Start a new simulation.", "strategic");
      return;
    }
    resetRun();
    setStage("negotiating");
    setShowReportDashboard(false);
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
        analysis: {
          ...(analysis.judge || {}),
          metric_events: metricEventHistory,
          run_history: runHistory,
          duration_seconds: analysis?.duration_seconds ?? runDurationSeconds,
          duration_hms: analysis?.duration_hms || formatDurationHms(analysis?.duration_seconds ?? runDurationSeconds),
        },
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
    a.download = `Program_Counsellor_Report_${Date.now()}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  };

  const renderTruncatedList = (items, title) => (
    <ul>
      {items.map((item, index) => {
        const text = String(item || "").trim();
        const shouldTruncate = text.length > PILLAR_ITEM_TRUNCATE;
        const preview = shouldTruncate ? `${text.slice(0, PILLAR_ITEM_TRUNCATE).trimEnd()}...` : text;
        return (
          <li key={`${title}-${index}-${text.slice(0, 16)}`}>
            <span>{preview}</span>
            {shouldTruncate && (
              <button
                type="button"
                className="inlineMoreBtn"
                onClick={() => setExpandedContent({ title, text })}
              >
                more
              </button>
            )}
          </li>
        );
      })}
      {!items.length && <li className="emptyItem">No insights available.</li>}
    </ul>
  );

  return (
    <main className={`app stage-${stage}`}>
      <img className="hero-bg" src={bgUrl} alt="" aria-hidden="true" />
      <div className="sceneOverlay" />

      {stage === "idle" && (
        <section className="hero">
          <h1>Negotia</h1>
          <p className="subtitle">AI Bout Arena: Program Counselling</p>
          <div className="inputRow">
            <input
              type="url"
              value={programUrl}
              onChange={(e) => setProgramUrl(e.target.value)}
              placeholder="Enter Program URL here..."
            />
            <button onClick={startNegotiation}>Agent vs Agent</button>
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
          <div className="activationContent">
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
          </div>
          <div className="activationReflection" aria-hidden="true">
            <h2>Arena Activation</h2>
            <div className="activationSteps">
              {ACTIVATION_STEPS.map((step, index) => (
                <p key={`ref-${step}`} className={index <= activationIndex ? "active" : ""}>
                  {step}
                </p>
              ))}
            </div>
          </div>
        </section>
      )}

      {(stage === "negotiating" || (stage === "completed" && !showReportDashboard)) && (
        <section className="arenaScene">
          {stage === "completed" && !showReportDashboard && (
            <div className="arenaBottomActions">
              <button className="ghostBtn viewReportBtn" onClick={() => setShowReportDashboard(true)}>
                View Report
              </button>
            </div>
          )}
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
              <h3>Program Counseller</h3>
              <p>{`${counsellorName || "Admissions Counsellor"}, ${program?.program_name || "Program"}`}</p>
            </article>
            <article className={`agentIdentity student ${momentumValue < 40 ? "glow" : ""}`}>
              <h3>Prospective Student</h3>
              <p>{`${persona?.name || "Student"}, ${formatArchetype(persona)}`}</p>
            </article>
          </div>

          <div className="projectionLane" ref={projectionRef}>
            {allCards.map((msg, idx) => (
              <article key={`${msg.id || idx}`} className={`projectionCard ${msg.agent} ${msg.draft ? "draft" : ""}`}>
                <header>
                  <div className="speakerMeta">
                    <strong>{msg.agent === "counsellor" ? "Program Counseller" : "Prospective Student"}</strong>
                    <span>
                      {msg.agent === "counsellor"
                        ? `${counsellorName || "Admissions Counsellor"}, ${program?.program_name || "Program"}`
                        : `${persona?.name || "Student"}, ${formatArchetype(persona)}`}
                    </span>
                  </div>
                  <span>{msg.round ? `Round ${msg.round}` : "Streaming"}</span>
                </header>
                <p>{msg.content}</p>
                {msg.agent === "student" && msg.internal_thought && (
                  <button
                    type="button"
                    className="thoughtBtn"
                    onClick={() => setExpandedContent({ title: "Internal Thought", text: msg.internal_thought })}
                  >
                    Internal Thought
                  </button>
                )}
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
          {stage === "negotiating" && (
            <div className={`metricsRibbon bottomRibbon ${(metrics?.close_probability ?? 0) > 80 ? "glow" : ""}`}>
              {renderMetricChips()}
            </div>
          )}
        </section>
      )}

      {stage === "completed" && analysis && showReportDashboard && (
        <section className="resultOverlay">
          <div className="resultCard">
            <div className="resultScrollBody">
              <header className="outcomeSummaryCard">
                <h2>{outcomeHeadline}</h2>
                <h3>Final Score: {analysis?.judge?.negotiation_score ?? 0} / 100</h3>
                <p>{analysis?.judge?.why || "Simulation completed."}</p>
                <div className="finalMetricChips">
                  <span className={`metricChip commitmentChip ${chipStateClass(commitmentSignalState(analysis?.judge?.commitment_signal))}`}>
                    <span className="statusDot" />
                    {COMMITMENT_LABELS[analysis?.judge?.commitment_signal] || COMMITMENT_LABELS.none}
                  </span>
                  <span className="metricChip">Enrollment Likelihood {analysis?.judge?.enrollment_likelihood ?? 0}%</span>
                  <span className="metricChip">Trust Delta {analysis?.judge?.trust_delta ?? 0}</span>
                  <span className="metricChip">Duration {analysis?.duration_hms || formatDurationHms(runDurationSeconds)}</span>
                </div>
              </header>

              <section className="personaTopCard">
                <div className="personaIdentity">
                  <span className="personaAvatar">{(persona?.name || "P").slice(0, 1).toUpperCase()}</span>
                  <div>
                    <h4>{persona?.name || "Prospective Student"}</h4>
                    <p>{formatArchetype(persona)}</p>
                  </div>
                </div>
                <div className="personaDetailRow">
                  <span><strong>Career Stage:</strong> {formatCareerStage(persona?.career_stage)}</span>
                  <span><strong>Risk Tolerance:</strong> {toTitleCase(persona?.risk_tolerance || "n/a")}</span>
                  <span><strong>Primary Objections:</strong> {(persona?.primary_objections || []).slice(0, 2).join(", ") || "n/a"}</span>
                </div>
              </section>

              <section className="primaryObjectionAlert">
                <div className="objectionTitle">Primary Unresolved Objection</div>
                <p>{analysis?.judge?.primary_unresolved_objection || "n/a"}</p>
              </section>

              {retryPerformance && (
                <section className="retryPerformanceCard">
                  <div className="retryCardHeader">
                    <h4>Performance Progression</h4>
                    <span className="retryActiveBadge">Retry Analysis</span>
                  </div>
                  <div className="retryCardBody">
                    <div className="runScoreBlocks">
                      <div className="runScoreBlock">
                        <span>Run 1</span>
                        <strong>{retryPerformance.baseline}</strong>
                      </div>
                      <div className="runScoreBlock">
                        <span>Run {retryPerformance.latest.runNumber}</span>
                        <strong>{retryPerformance.latest.score}</strong>
                      </div>
                    </div>
                    <div className={`retryDeltaCallout ${retryPerformance.latest.deltaFromPrevious >= 0 ? "improved" : "degraded"}`}>
                      <div className="deltaValue">
                        {retryPerformance.latest.deltaFromPrevious >= 0 ? "↗" : "↘"} {retryPerformance.latest.deltaFromPrevious >= 0 ? "+" : ""}
                        {retryPerformance.latest.deltaFromPrevious}
                      </div>
                      <div className="deltaMeta">
                        <span>Vs previous run</span>
                        <span>Baseline {retryPerformance.latest.deltaFromBaseline >= 0 ? "+" : ""}{retryPerformance.latest.deltaFromBaseline}</span>
                      </div>
                    </div>
                    <div className="sparklineWrap">
                      <div className="sparklineHeader">
                        <span>Progress</span>
                        <span className="bestRunBadge">Best {retryPerformance.bestScore}</span>
                      </div>
                      <div className="sparklineBars">
                        {retryPerformance.points.map((run) => (
                          <div key={run.label} className={`sparklineBar ${run.isBest ? "best" : ""}`} style={{ height: `${Math.max(18, run.score)}%` }}>
                            <span>R{run.runNumber}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </section>
              )}

              <div className="pillarsGrid">
                <article className="pillarCard">
                  <h4>Key Turning Points</h4>
                  <div className="pillarContent">
                    {renderTruncatedList(analysis?.judge?.pivotal_moments || [], "Key Turning Points")}
                  </div>
                </article>
                <article className="pillarCard">
                  <h4>Strengths</h4>
                  <div className="pillarContent">
                    {renderTruncatedList(analysis?.judge?.strengths || [], "Strengths")}
                  </div>
                </article>
                <article className="pillarCard">
                  <h4>Mistakes</h4>
                  <div className="pillarContent">
                    {renderTruncatedList(analysis?.judge?.mistakes || [], "Mistakes")}
                  </div>
                </article>
                <article className="pillarCard">
                  <h4>Opportunities</h4>
                  <div className="pillarContent">
                    {renderTruncatedList(analysis?.judge?.skill_recommendations || [], "Opportunities")}
                  </div>
                </article>
              </div>

              <article className="coachingInsightsPanel">
                <h4>Coaching Insights</h4>
                <div className="insightRows">
                  {(analysis?.judge?.skill_recommendations || []).map((insight, index) => (
                    <div key={`insight-${index}`} className="insightRow">
                      {insight}
                    </div>
                  ))}
                  {!(analysis?.judge?.skill_recommendations || []).length && (
                    <div className="insightRow">No coaching insights available.</div>
                  )}
                </div>
              </article>

              <article className="metricEventsPanel">
                <div className="timelineHeaderRow">
                  <h4>Conversation Metrics Timeline</h4>
                  <div className="timelineLegend">
                    <span><i className="legendDot positive" /> Positive</span>
                    <span><i className="legendDot negative" /> Negative</span>
                    <span><i className="legendDot strategic" /> Strategic</span>
                  </div>
                </div>
                <div className="timelineTrack">
                  {roundInsights.length === 0 ? (
                    <div className="metricEventItem">No metric events captured.</div>
                  ) : (
                    roundInsights.map((row, index) => (
                      <button
                        key={`round-${row.round}`}
                        className={`timelineNode ${activeRoundInsight?.round === row.round ? "active" : ""}`}
                        onClick={() => setSelectedTimelineRound(row.round)}
                        type="button"
                      >
                        <span className="roundNode">Round {row.round}</span>
                        <span className="roundDelta">{row.compactDelta}</span>
                        <div className="roundMetricChips">
                          {row.metricChips.map((chip, chipIndex) => (
                            <span key={`${row.round}-${chipIndex}`} className={`miniMetricChip ${chip.tone}`}>
                              {chip.text}
                            </span>
                          ))}
                          {!row.metricChips.length && <span className="miniMetricChip strategic">No shift</span>}
                        </div>
                        {index < roundInsights.length - 1 && <span className="timelineConnector" />}
                      </button>
                    ))
                  )}
                </div>
                {activeRoundInsight && (
                  <div className="timelineDetailCard">
                    <div><strong>Emotional Shift:</strong> {activeRoundInsight.emotionalShift}</div>
                    <div><strong>Objection Spike:</strong> {activeRoundInsight.objectionSpike}</div>
                    <div><strong>Trust Change:</strong> {activeRoundInsight.trustDelta >= 0 ? "+" : ""}{activeRoundInsight.trustDelta}</div>
                    <div><strong>Resistance Change:</strong> {activeRoundInsight.resistanceDelta >= 0 ? "+" : ""}{activeRoundInsight.resistanceDelta}</div>
                    <div><strong>Close Probability Shift:</strong> {activeRoundInsight.closeDelta >= 0 ? "+" : ""}{activeRoundInsight.closeDelta}</div>
                    <div><strong>Tactical Move:</strong> {activeRoundInsight.tacticalMove}</div>
                  </div>
                )}
              </article>
            </div>
            <div className="resultActions stickyActions">
              <button className="downloadBtn" onClick={downloadReport}>
                Download Coaching Report (PDF)
              </button>
              <button className="downloadBtn" onClick={retrySimulation}>
                Retry to Improve
              </button>
              <button className={`ghostBtn ${showRestartPulse ? "pulse" : ""}`} onClick={startNewSimulation}>
                Start New Simulation
              </button>
            </div>
          </div>
        </section>
      )}
      {expandedContent && (
        <div className="contentModalOverlay" onClick={() => setExpandedContent(null)} role="presentation">
          <section className="contentModalCard" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
            <header>
              <h4>{expandedContent.title}</h4>
              <button type="button" onClick={() => setExpandedContent(null)} aria-label="Close detail">
                X
              </button>
            </header>
            <div className="contentModalBody">
              <p>{expandedContent.text}</p>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export default App;

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import CopilotWidget from "./components/CopilotWidget";
import "./App.css";

const BACKEND_URL = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/negotiate";

const ACTIVATION_STEPS = [
  "Preparing Duel Arena...",
  "Calibrating Negotiation Reflexes...",
  "Injecting Persona DNA...",
  "Loading Psychological Profile...",
  "Entering the CloseWire...",
];
const HINDI_ACTIVATION_STEPS = [
  "à¤¡à¥à¤¯à¥‚à¤² à¤à¤°à¥€à¤¨à¤¾ à¤¤à¥ˆà¤¯à¤¾à¤° à¤¹à¥‹ à¤°à¤¹à¤¾ à¤¹à¥ˆ...",
  "à¤¨à¥‡à¤—à¥‹à¤¶à¤¿à¤à¤¶à¤¨ à¤°à¤¿à¤«à¥à¤²à¥‡à¤•à¥à¤¸ à¤•à¥ˆà¤²à¤¿à¤¬à¥à¤°à¥‡à¤Ÿ à¤¹à¥‹ à¤°à¤¹à¥‡ à¤¹à¥ˆà¤‚...",
  "à¤ªà¤°à¥à¤¸à¥‹à¤¨à¤¾ à¤¡à¥€à¤à¤¨à¤ à¤²à¥‹à¤¡ à¤¹à¥‹ à¤°à¤¹à¤¾ à¤¹à¥ˆ...",
  "à¤®à¤¨à¥‹à¤µà¥ˆà¤œà¥à¤žà¤¾à¤¨à¤¿à¤• à¤ªà¥à¤°à¥‹à¤«à¤¾à¤‡à¤² à¤µà¤¿à¤¶à¥à¤²à¥‡à¤·à¤¿à¤¤ à¤¹à¥‹ à¤°à¤¹à¥€ à¤¹à¥ˆ...",
  "à¤•à¥à¤²à¥‹à¤œà¤µà¤¾à¤¯à¤° à¤®à¥‡à¤‚ à¤ªà¥à¤°à¤µà¥‡à¤¶ à¤¹à¥‹ à¤°à¤¹à¤¾ à¤¹à¥ˆ...",
];
const COMMITMENT_LABELS = {
  none: "No Commitment",
  soft_commitment: "Exploring Enrollment",
  conditional_commitment: "Conditional Yes",
  strong_commitment: "Confirmed Enrollment",
};
const LIVE_PROCESSING_LABELS = ["Analyzing Tone...", "Calculating Trust..."];
const SILENCE_AUTO_SEND_MS = 5000;
const SILENCE_PROMPT_MS = 10000;
const PIPELINE_OPTIONS = [
  { id: "ai_vs_ai", title: "LAB: Agent vs Agent", subtitle: "Autonomous counsellor and prospect simulation.", status: "active" },
  { id: "human_vs_ai", title: "GYM: Human vs Agent", subtitle: "You speak as counsellor, AI responds as prospect.", status: "active" },
  { id: "agent_powered_human_vs_ai", title: "ARENA: Agent Powered Human vs Agent", subtitle: "Voice-first counsellor with live Agent cues.", status: "active" },
];
const ARCHETYPE_CARDS = [
  { id: "random", icon: "??", title: "Random Profile", profile: "Let CloseWire pick one profile at random.", accent: "#9aa6c8" },
  { id: "desperate_switcher", icon: "SW", title: "Desperate Switcher", profile: "Urgent career pivot, seeks fast outcomes.", accent: "#ff8f5c" },
  { id: "stagnant_pro", icon: "SP", title: "Stagnant Pro", profile: "Plateaued growth, wants clear progression.", accent: "#5ec7ff" },
  { id: "credential_hunter", icon: "CH", title: "Credential Hunter", profile: "Status-driven, prioritizes recognition signals.", accent: "#c38dff" },
  { id: "intellectual_buyer", icon: "IB", title: "Intellectual Buyer", profile: "Dissects syllabus depth; demands technical specificity.", accent: "#6fd4ff" },
  { id: "fomo_victim", icon: "FV", title: "FOMO Victim", profile: "Fear-driven urgency, reacts to momentum.", accent: "#ff6f95" },
  { id: "drifter", icon: "DR", title: "Drifter", profile: "Low clarity, needs structure and direction.", accent: "#74d9a4" },
  { id: "skeptical_shopper", icon: "SK", title: "Skeptical Shopper", profile: "हिंदी वक्ता: प्रमाण मांगता है और दावों को चुनौती देता है।", accent: "#f4c15d" },
];
const DEFAULT_VOICE_PROFILE_MAPPING = {
  voice_preferences: {
    male: ["Google UK English Male", "Microsoft David", "David", "Male"],
    female: ["Google US English", "Microsoft Zira", "Zira", "Female"],
  },
  hindi_voice_preferences: {
    male: ["Google हिन्दी", "Microsoft Heera", "Hindi Male"],
    female: ["Google हिन्दी", "Microsoft Heera", "Hindi Female"],
  },
};

const PILLAR_ITEM_TRUNCATE = 120;
const STUDENT_CONTROL_PREFIXES = [
  "INTERNAL_THOUGHT:",
  "UPDATED_STATS:",
  "UPDATED_STATE:",
  "EMOTIONAL_STATE:",
  "STRATEGIC_INTENT:",
];
const isHumanDrivenPipeline = (mode) => mode === "human_vs_ai" || mode === "agent_powered_human_vs_ai";

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

const commitmentReportState = (signal) => {
  const normalized = String(signal || "").toLowerCase();
  if (normalized === "none") return "danger";
  if (normalized === "soft_commitment") return "warning";
  return "success";
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
  const [pendingDownloadReport, setPendingDownloadReport] = useState(false);
  const [pendingMode, setPendingMode] = useState("ai_vs_ai");
  const [pendingArchetype, setPendingArchetype] = useState("desperate_switcher");
  const [expandedContent, setExpandedContent] = useState(null);
  const [showReportDashboard, setShowReportDashboard] = useState(false);
  const [chipFlash, setChipFlash] = useState({});
  const [runDurationSeconds, setRunDurationSeconds] = useState(0);
  const [negotiationMode, setNegotiationMode] = useState("ai_vs_ai");
  const [micState, setMicState] = useState("inactive");
  const [liveTranscript, setLiveTranscript] = useState("");
  const [micPermissionStatus, setMicPermissionStatus] = useState("prompt");
  const [humanInputText, setHumanInputText] = useState("");
  const [processingLabelIndex, setProcessingLabelIndex] = useState(0);
  const [waveformLevel, setWaveformLevel] = useState(0);
  const [studentImageSrc, setStudentImageSrc] = useState("");
  const [voiceProfileMapping, setVoiceProfileMapping] = useState(DEFAULT_VOICE_PROFILE_MAPPING);
  const [selectedPipeline, setSelectedPipeline] = useState("ai_vs_ai");
  const [selectedArchetype, setSelectedArchetype] = useState("desperate_switcher");
  const [showControlModal, setShowControlModal] = useState(false);
  const [copilotData, setCopilotData] = useState(null);
  const [copilotState, setCopilotState] = useState("idle");
  const [copilotPinnedSuggestion, setCopilotPinnedSuggestion] = useState("");
  const [isAutoSendEnabled, setIsAutoSendEnabled] = useState(true);

  const wsRef = useRef(null);
  const projectionRef = useRef(null);
  const prevMetricsRef = useRef(null);
  const toastTimerRef = useRef({});
  const uiToastTimerRef = useRef({});
  const pendingThoughtsRef = useRef({});
  const chipFlashTimerRef = useRef({});
  const runStartEpochRef = useRef(null);
  const recognitionRef = useRef(null);
  const silenceTimerRef = useRef(null);
  const inactivityTimerRef = useRef(null);
  const silencePromptTimerRef = useRef(null);
  const processingLabelTimerRef = useRef(null);
  const liveTranscriptRef = useRef("");
  const humanInputRef = useRef(null);
  const committedTranscriptRef = useRef("");
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const waveformRafRef = useRef(null);
  const isTtsSpeakingRef = useRef(false);
  const utteranceRef = useRef(null);
  const selectedVoiceRef = useRef(null);
  const selectedVoiceNameRef = useRef("");
  const ttsUnlockTimerRef = useRef(null);
  const ttsWatchdogRef = useRef(null);
  const processingFailSafeTimerRef = useRef(null);
  const isStartingRecognitionRef = useRef(false);
  const visibilityPausedRef = useRef(false);
  const stageRef = useRef("idle");
  const modeRef = useRef("ai_vs_ai");
  const micStateRef = useRef("inactive");
  const isAutoSendEnabledRef = useRef(true);
  const micPausedRef = useRef(false);
  const speechRecognitionCtor = typeof window !== "undefined"
    ? (window.SpeechRecognition || window.webkitSpeechRecognition || null)
    : null;
  const isHumanMode = isHumanDrivenPipeline(negotiationMode);
  const isAgentPoweredMode = negotiationMode === "agent_powered_human_vs_ai";
  const profileImageName = String(persona?.archetype_id || "student-placeholder").trim().toLowerCase();
  const personaLanguageStyle = String(persona?.language_style || "").trim().toLowerCase();
  const isHindiPersona = personaLanguageStyle.includes("hindi")
    || (isHumanMode && profileImageName === "skeptical_shopper");
  const inferredGender = useMemo(() => {
    const explicit = String(persona?.gender || "").trim().toLowerCase();
    if (explicit === "male" || explicit === "female") return explicit;
    return "male";
  }, [persona?.gender]);

  useEffect(() => {
    isAutoSendEnabledRef.current = isAutoSendEnabled;
    // Sync pause ref with active state to prevent desync
    micPausedRef.current = !isAutoSendEnabled;
    // eslint-disable-next-line no-console
    console.log("[MIC-DEBUG] Syncing micPausedRef to", !isAutoSendEnabled, "bases on isAutoSendEnabled:", isAutoSendEnabled);

    if (!isAutoSendEnabled && inactivityTimerRef.current) {
      clearTimeout(inactivityTimerRef.current);
      inactivityTimerRef.current = null;
    }
  }, [isAutoSendEnabled]);

  useEffect(() => {
    stageRef.current = stage;
  }, [stage]);

  useEffect(() => {
    modeRef.current = negotiationMode;
  }, [negotiationMode]);

  useEffect(() => {
    micStateRef.current = micState;
  }, [micState]);

  useEffect(() => {
    const cachedToken = sessionStorage.getItem("negotiator_auth_token");
    if (cachedToken) {
      setAuthToken(cachedToken);
    }
  }, []);

  useEffect(() => {
    if (authToken) {
      sessionStorage.setItem("negotiator_auth_token", authToken);
    } else {
      sessionStorage.removeItem("negotiator_auth_token");
    }
  }, [authToken]);

  const clearMicTimers = () => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    if (inactivityTimerRef.current) {
      clearTimeout(inactivityTimerRef.current);
      inactivityTimerRef.current = null;
    }
    if (silencePromptTimerRef.current) {
      clearTimeout(silencePromptTimerRef.current);
      silencePromptTimerRef.current = null;
    }
  };

  const clearProcessingTicker = () => {
    if (processingLabelTimerRef.current) {
      clearInterval(processingLabelTimerRef.current);
      processingLabelTimerRef.current = null;
    }
  };

  const clearTtsTimers = () => {
    if (ttsUnlockTimerRef.current) {
      clearTimeout(ttsUnlockTimerRef.current);
      ttsUnlockTimerRef.current = null;
    }
    if (ttsWatchdogRef.current) {
      clearInterval(ttsWatchdogRef.current);
      ttsWatchdogRef.current = null;
    }
  };

  const clearProcessingFailSafe = () => {
    if (processingFailSafeTimerRef.current) {
      clearTimeout(processingFailSafeTimerRef.current);
      processingFailSafeTimerRef.current = null;
    }
  };

  const hardStopAudioAndMic = useCallback(() => {
    try {
      stopRecognition();
    } catch (error) {
      // noop
    }
    try {
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    } catch (error) {
      // noop
    }
    clearTtsTimers();
    clearProcessingTicker();
    clearProcessingFailSafe();
    isTtsSpeakingRef.current = false;
    isStartingRecognitionRef.current = false;
    visibilityPausedRef.current = false;
    utteranceRef.current = null;
    window.currentUtterance = null;
    setMicState("inactive");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopWaveform = () => {
    if (waveformRafRef.current) {
      cancelAnimationFrame(waveformRafRef.current);
      waveformRafRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => { });
      audioContextRef.current = null;
    }
    analyserRef.current = null;
    setWaveformLevel(0);
  };

  const stopRecognition = () => {
    // eslint-disable-next-line no-console
    console.log("[MIC-DEBUG] stopRecognition called");
    const recognition = recognitionRef.current;
    if (!recognition) {
      setMicState((current) => (current === "processing" || current === "locked" ? current : "inactive"));
      return;
    }
    try {
      recognition.onend = null;
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onspeechend = null;
      recognition.stop();
    } catch (error) {
      try {
        recognition.abort();
      } catch (abortError) {
        // noop
      }
    }
    recognitionRef.current = null;
    isStartingRecognitionRef.current = false;
    stopWaveform();
    clearMicTimers();
    setMicState((current) => (current === "processing" || current === "locked" ? current : "inactive"));
  };

  const selectSpeechVoice = useCallback(() => {
    if (selectedVoiceRef.current) return selectedVoiceRef.current;
    const synth = window.speechSynthesis;
    if (!synth) return null;
    const voices = synth.getVoices() || [];
    if (!voices.length) return null;

    const needsHindiVoice = isHindiPersona;
    if (needsHindiVoice) {
      const hindiPrefs = voiceProfileMapping?.hindi_voice_preferences || DEFAULT_VOICE_PROFILE_MAPPING.hindi_voice_preferences;
      const preferredHindiNames = hindiPrefs[inferredGender] || [];
      for (const preference of preferredHindiNames) {
        const token = String(preference || "").toLowerCase();
        if (!token) continue;
        const matchedHindiPreferred = voices.find((voice) => String(voice.name || "").toLowerCase().includes(token));
        if (matchedHindiPreferred) {
          selectedVoiceRef.current = matchedHindiPreferred;
          selectedVoiceNameRef.current = `${matchedHindiPreferred.name} (${matchedHindiPreferred.lang})`;
          return matchedHindiPreferred;
        }
      }
      const hindiVoice = voices.find((voice) => /^hi-in/i.test(String(voice.lang || "")))
        || voices.find((voice) => /hindi|hi-in/i.test(`${voice.name || ""} ${voice.lang || ""}`));
      if (hindiVoice) {
        selectedVoiceRef.current = hindiVoice;
        selectedVoiceNameRef.current = `${hindiVoice.name} (${hindiVoice.lang})`;
        return hindiVoice;
      }
    }

    const preferences = voiceProfileMapping?.voice_preferences || DEFAULT_VOICE_PROFILE_MAPPING.voice_preferences;
    const preferredNames = preferences[inferredGender] || [];
    for (const preference of preferredNames) {
      const token = String(preference || "").toLowerCase();
      if (!token) continue;
      const matched = voices.find((voice) => String(voice.name || "").toLowerCase().includes(token));
      if (matched) {
        selectedVoiceRef.current = matched;
        selectedVoiceNameRef.current = `${matched.name} (${matched.lang})`;
        return matched;
      }
    }

    if (inferredGender === "male") {
      const maleLike = voices.find((voice) => /male|david|mark|daniel|george/i.test(String(voice.name || "")));
      if (maleLike) {
        selectedVoiceRef.current = maleLike;
        selectedVoiceNameRef.current = `${maleLike.name} (${maleLike.lang})`;
        return maleLike;
      }
    } else {
      const femaleLike = voices.find((voice) => /female|zira|heera|susan|hazel|sarah/i.test(String(voice.name || "")));
      if (femaleLike) {
        selectedVoiceRef.current = femaleLike;
        selectedVoiceNameRef.current = `${femaleLike.name} (${femaleLike.lang})`;
        return femaleLike;
      }
    }

    const englishIndian = voices.find((voice) => /^en-in/i.test(String(voice.lang || "")));
    if (englishIndian) {
      selectedVoiceRef.current = englishIndian;
      selectedVoiceNameRef.current = `${englishIndian.name} (${englishIndian.lang})`;
      return englishIndian;
    }
    const english = voices.find((voice) => /^en/i.test(String(voice.lang || "")));
    selectedVoiceRef.current = english || voices[0];
    selectedVoiceNameRef.current = selectedVoiceRef.current
      ? `${selectedVoiceRef.current.name} (${selectedVoiceRef.current.lang})`
      : "";
    return selectedVoiceRef.current;
  }, [inferredGender, isHindiPersona, voiceProfileMapping]);

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
  const liveModeNeedsTextFallback = isHumanMode && (!speechRecognitionCtor || micPermissionStatus === "denied");
  const sentimentChipState = useMemo(() => {
    const sentiment = String(metrics?.sentiment_indicator || "").toLowerCase();
    if (sentiment.includes("positive") || sentiment.includes("excited")) return "success";
    if (sentiment.includes("negative") || sentiment.includes("frustrated")) return "danger";
    return "warning";
  }, [metrics?.sentiment_indicator]);
  const activationTitle = useMemo(() => {
    if (selectedArchetype === "skeptical_shopper") {
      if (negotiationMode === "human_vs_ai") return "à¤¹à¥à¤¯à¥‚à¤®à¤¨ à¤¬à¤¨à¤¾à¤® à¤à¤œà¥‡à¤‚à¤Ÿ à¤¡à¥à¤¯à¥‚à¤² à¤¸à¤•à¥à¤°à¤¿à¤¯";
      if (negotiationMode === "agent_powered_human_vs_ai") return "à¤à¤œà¥‡à¤‚à¤Ÿ à¤…à¤¸à¤¿à¤¸à¥à¤Ÿà¥‡à¤¡ à¤¹à¥à¤¯à¥‚à¤®à¤¨ à¤¬à¤¨à¤¾à¤® à¤à¤œà¥‡à¤‚à¤Ÿ à¤¡à¥à¤¯à¥‚à¤² à¤¸à¤•à¥à¤°à¤¿à¤¯";
      return "à¤à¤œà¥‡à¤‚à¤Ÿ à¤¬à¤¨à¤¾à¤® à¤à¤œà¥‡à¤‚à¤Ÿ à¤¡à¥à¤¯à¥‚à¤² à¤¸à¤•à¥à¤°à¤¿à¤¯";
    }
    if (negotiationMode === "human_vs_ai") return "Human vs Agent Duel Activated";
    if (negotiationMode === "agent_powered_human_vs_ai") return "Agent Assisted Human vs Agent Duel Activated";
    return "Agent vs Agent Duel Activated";
  }, [negotiationMode, selectedArchetype]);
  const activationSteps = selectedArchetype === "skeptical_shopper" ? HINDI_ACTIVATION_STEPS : ACTIVATION_STEPS;

  useEffect(() => {
    if (!isAgentPoweredMode) {
      setCopilotState("idle");
      setCopilotData(null);
      setCopilotPinnedSuggestion("");
      return;
    }
    if (micState === "listening" && copilotState === "ready") {
      setCopilotState("minimized");
    }
  }, [copilotState, isAgentPoweredMode, micState]);

  const handleApplyCopilotSuggestion = (suggestionText) => {
    const text = String(suggestionText || "").trim();
    if (!text) return;
    setCopilotPinnedSuggestion(text);
    if (!liveModeNeedsTextFallback) return;
    setHumanInputText(text);
    setLiveTranscript(text);
    liveTranscriptRef.current = text;
    if (humanInputRef.current) {
      humanInputRef.current.focus();
    }
  };

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

  const baseUrl = process.env.PUBLIC_URL || "";
  const isTransparentStage = stage === "negotiating" || stage === "completed";

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
    hardStopAudioAndMic();
    clearMicTimers();
    setMicState("inactive");
    setLiveTranscript("");
    liveTranscriptRef.current = "";
    committedTranscriptRef.current = "";
    setHumanInputText("");
    setProcessingLabelIndex(0);
    setWaveformLevel(0);
    setCopilotData(null);
    setCopilotState("idle");
    setCopilotPinnedSuggestion("");
  };

  useEffect(
    () => () => {
      Object.values(uiToastTimerRef.current).forEach((timer) => clearTimeout(timer));
      Object.values(toastTimerRef.current).forEach((timer) => clearTimeout(timer));
      Object.values(chipFlashTimerRef.current).forEach((timer) => clearTimeout(timer));
      hardStopAudioAndMic();
      clearMicTimers();
    },
    [hardStopAudioAndMic]
  );

  useEffect(() => {
    liveTranscriptRef.current = liveTranscript;
  }, [liveTranscript]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const shutdown = () => hardStopAudioAndMic();
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        if (isHumanDrivenPipeline(modeRef.current) && stageRef.current === "negotiating") {
          visibilityPausedRef.current = true;
          stopRecognition();
          if (micStateRef.current !== "locked" && micStateRef.current !== "processing") {
            setMicState("inactive");
          }
          return;
        }
        shutdown();
        return;
      }
      if (
        document.visibilityState === "visible"
        && visibilityPausedRef.current
        && isHumanDrivenPipeline(modeRef.current)
        && stageRef.current === "negotiating"
        && micStateRef.current !== "locked"
        && micStateRef.current !== "processing"
        && !isTtsSpeakingRef.current
        && !window.speechSynthesis?.speaking
      ) {
        visibilityPausedRef.current = false;
        setMicState("inactive");
      }
    };
    window.addEventListener("beforeunload", shutdown);
    window.addEventListener("pagehide", shutdown);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("beforeunload", shutdown);
      window.removeEventListener("pagehide", shutdown);
      document.removeEventListener("visibilitychange", onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hardStopAudioAndMic]);

  useEffect(() => {
    selectedVoiceRef.current = null;
  }, [inferredGender, persona?.name]);

  useEffect(() => {
    const base = process.env.PUBLIC_URL || "";
    setStudentImageSrc(`${base}/${profileImageName}.png`);
  }, [profileImageName]);

  useEffect(() => {
    let cancelled = false;
    const base = process.env.PUBLIC_URL || "";
    fetch(`${base}/browservoice_profile_mapping.json`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (cancelled || !payload || typeof payload !== "object") return;
        setVoiceProfileMapping({
          ...DEFAULT_VOICE_PROFILE_MAPPING,
          ...payload,
          voice_preferences: {
            ...DEFAULT_VOICE_PROFILE_MAPPING.voice_preferences,
            ...(payload.voice_preferences || {}),
          },
          hindi_voice_preferences: {
            ...DEFAULT_VOICE_PROFILE_MAPPING.hindi_voice_preferences,
            ...(payload.hindi_voice_preferences || {}),
          },
        });
      })
      .catch(() => { });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const startProcessingTicker = () => {
    clearProcessingTicker();
    setProcessingLabelIndex(0);
    processingLabelTimerRef.current = setInterval(() => {
      setProcessingLabelIndex((current) => (current + 1) % LIVE_PROCESSING_LABELS.length);
    }, 900);
  };

  const armSilencePromptTimer = () => {
    if (silencePromptTimerRef.current) clearTimeout(silencePromptTimerRef.current);
    silencePromptTimerRef.current = setTimeout(() => {
      if (isHumanDrivenPipeline(modeRef.current) && stageRef.current === "negotiating" && micStateRef.current === "listening") {
        pushUiToast("Are you there? Please press Send manually.", "strategic", 3600);
      }
    }, SILENCE_PROMPT_MS);
  };

  const sendHumanInput = (rawText) => {
    if (!isHumanDrivenPipeline(modeRef.current)) return;
    if (window.speechSynthesis?.speaking) return;
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      pushUiToast("Connection is not ready for live coaching.");
      return;
    }
    const text = String(rawText ?? liveTranscriptRef.current ?? humanInputText).trim();
    if (!text) {
      pushUiToast("Speak or type a message before sending.", "strategic");
      return;
    }
    if (isTtsSpeakingRef.current) {
      pushUiToast("Please wait for student voice to finish.", "strategic");
      return;
    }
    clearMicTimers();
    setMicState("processing");
    startProcessingTicker();
    socket.send(JSON.stringify({ type: "human_input", text }));
    clearProcessingFailSafe();
    processingFailSafeTimerRef.current = setTimeout(() => {
      if (micStateRef.current === "processing" && isHumanDrivenPipeline(modeRef.current) && stageRef.current === "negotiating") {
        setMicState("inactive");
        clearProcessingTicker();
        pushUiToast("Student response took too long. Mic resumed for retry.", "strategic", 3200);
      }
    }, 20000);
    setLiveTranscript("");
    liveTranscriptRef.current = "";
    committedTranscriptRef.current = "";
    setHumanInputText("");
    stopRecognition();
  };

  const armAutoSendTimer = () => {
    if (!isHumanDrivenPipeline(modeRef.current)) return;
    if (micStateRef.current !== "listening") return;
    if (!isAutoSendEnabledRef.current) return;
    if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current);
    inactivityTimerRef.current = setTimeout(() => {
      if (!isHumanDrivenPipeline(modeRef.current) || micStateRef.current !== "listening") return;
      if (!isAutoSendEnabledRef.current) return;
      if (window.speechSynthesis?.speaking || isTtsSpeakingRef.current) return;
      const candidate = String(liveTranscriptRef.current || "").trim();
      if (candidate) {
        sendHumanInput(candidate);
      }
    }, SILENCE_AUTO_SEND_MS);
  };

  const speakStudentTurn = (text, emotionalState = "calm") => {
    const synth = window.speechSynthesis;
    if (!synth || !String(text || "").trim()) {
      setMicState("inactive");
      return;
    }
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(String(text).trim());
    if (isHindiPersona) {
      utterance.lang = "hi-IN";
    } else {
      utterance.lang = "en-GB";
    }
    const voice = selectSpeechVoice();
    if (voice) utterance.voice = voice;
    if (selectedVoiceNameRef.current) {
      // eslint-disable-next-line no-console
      console.info("TTS voice selected", {
        persona: persona?.name || "student",
        inferredGender,
        voice: selectedVoiceNameRef.current,
      });
    }
    const emotion = String(emotionalState || "calm").toLowerCase();
    if (emotion === "frustrated") {
      utterance.rate = 1.1;
      utterance.pitch = 0.9;
    } else if (emotion === "excited") {
      utterance.rate = 1.1;
      utterance.pitch = 1.1;
    } else {
      utterance.rate = 1.0;
      utterance.pitch = 1.0;
    }
    utterance.onstart = () => {
      isTtsSpeakingRef.current = true;
      setMicState("locked");
      stopRecognition();
    };
    const finishSpeech = () => {
      if (!isTtsSpeakingRef.current && !utteranceRef.current) return;
      isTtsSpeakingRef.current = false;
      if (ttsUnlockTimerRef.current) {
        clearTimeout(ttsUnlockTimerRef.current);
        ttsUnlockTimerRef.current = null;
      }
      if (ttsWatchdogRef.current) {
        clearInterval(ttsWatchdogRef.current);
        ttsWatchdogRef.current = null;
      }
      utteranceRef.current = null;
      window.currentUtterance = null;
      if (stageRef.current === "negotiating" && isHumanDrivenPipeline(modeRef.current)) {
        setMicState("inactive");
      }
    };
    utterance.onend = finishSpeech;
    utterance.onerror = finishSpeech;
    utteranceRef.current = utterance;
    // Keep a hard reference to avoid Chrome GC ending speech early.
    window.currentUtterance = utterance;
    synth.speak(utterance);
    const expectedMs = Math.min(60000, Math.max(12000, utterance.text.length * 110));
    ttsUnlockTimerRef.current = setTimeout(() => {
      try {
        if (window.speechSynthesis?.speaking) {
          window.speechSynthesis.cancel();
        }
      } catch (error) {
        // noop
      }
      finishSpeech();
    }, expectedMs);
    ttsWatchdogRef.current = setInterval(() => {
      if (isTtsSpeakingRef.current && !window.speechSynthesis.speaking) {
        finishSpeech();
      }
    }, 250);
  };

  const startListening = async () => {
    // eslint-disable-next-line no-console
    console.log("[MIC-DEBUG] startListening called", {
      isHumanMode,
      stage,
      isStarting: isStartingRecognitionRef.current,
      isTtsSpeaking: isTtsSpeakingRef.current,
      micState: micStateRef.current,
      micPaused: micPausedRef.current
    });
    if (!isHumanMode || stage !== "negotiating") return;
    if (micPausedRef.current) return;
    if (isStartingRecognitionRef.current) return;
    if (isTtsSpeakingRef.current || window.speechSynthesis?.speaking || micStateRef.current === "locked" || micStateRef.current === "processing") return;
    if (!speechRecognitionCtor || micPermissionStatus === "denied") {
      setMicState("inactive");
      return;
    }
    isStartingRecognitionRef.current = true;
    stopRecognition();
    let stream;
    try {
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      if (AudioContextCtor && navigator.mediaDevices?.getUserMedia) {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const context = new AudioContextCtor();
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        audioContextRef.current = context;
        analyserRef.current = analyser;
        const data = new Uint8Array(analyser.frequencyBinCount);
        const tick = () => {
          if (!analyserRef.current) return;
          analyserRef.current.getByteFrequencyData(data);
          const avg = data.reduce((sum, value) => sum + value, 0) / data.length;
          setWaveformLevel(Math.max(0, Math.min(1, avg / 140)));
          waveformRafRef.current = requestAnimationFrame(tick);
        };
        waveformRafRef.current = requestAnimationFrame(tick);
      }
    } catch (error) {
      // Continue without waveform if audio analyser setup fails.
      stopWaveform();
    } finally {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
    }

    const recognition = new speechRecognitionCtor();
    recognition.continuous = true;
    recognition.interimResults = true;
    const shouldUseHindiRecognition = isHumanDrivenPipeline(modeRef.current) && isHindiPersona;
    recognition.lang = shouldUseHindiRecognition ? "hi-IN" : "en-IN";
    recognition.onstart = () => {
      setMicPermissionStatus("granted");
      setMicState("listening");
      armSilencePromptTimer();
      committedTranscriptRef.current = String(liveTranscriptRef.current || "").trim();
    };
    recognition.onresult = (event) => {
      let interim = "";
      let finalTextDelta = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result?.[0]?.transcript || "";
        if (result.isFinal) {
          finalTextDelta += `${transcript} `;
        } else {
          interim += transcript;
        }
      }
      if (finalTextDelta.trim()) {
        committedTranscriptRef.current = `${committedTranscriptRef.current} ${finalTextDelta}`.trim();
      }
      const merged = `${committedTranscriptRef.current} ${interim}`.trim();
      setLiveTranscript(merged);
      liveTranscriptRef.current = merged;
      setHumanInputText(merged);
      armSilencePromptTimer();
      armAutoSendTimer();
    };
    recognition.onspeechend = () => {
      armAutoSendTimer();
    };
    recognition.onerror = (event) => {
      const code = String(event?.error || "").toLowerCase();
      if (code === "not-allowed" || code === "service-not-allowed" || code === "permission-denied") {
        setMicPermissionStatus("denied");
        setMicState("inactive");
        pushUiToast("Microphone permission denied. Switched to text input mode.", "strategic", 3600);
      } else {
        setMicState("inactive");
      }
      stopRecognition();
    };
    recognition.onend = () => {
      // eslint-disable-next-line no-console
      console.log("[MIC-DEBUG] recognition.onend fired");
      setMicState((current) => (current === "processing" || current === "locked" ? current : "inactive"));
      stopWaveform();
      armAutoSendTimer();
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      isStartingRecognitionRef.current = false;
    } catch (error) {
      isStartingRecognitionRef.current = false;
      setMicState("inactive");
      stopRecognition();
    }
  };

  const ensureMicPermission = async () => {
    if (!isHumanMode) return "granted";
    if (!navigator.mediaDevices?.getUserMedia) return "prompt";
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      setMicPermissionStatus("granted");
      return "granted";
    } catch (error) {
      const name = String(error?.name || "").toLowerCase();
      if (name.includes("notallowed") || name.includes("permissiondenied")) {
        setMicPermissionStatus("denied");
        return "denied";
      }
      return "prompt";
    }
  };

  useEffect(() => {
    if (!window.speechSynthesis) return undefined;
    const bindVoices = () => {
      if (!selectedVoiceRef.current) {
        selectSpeechVoice();
      }
    };
    bindVoices();
    window.speechSynthesis.addEventListener("voiceschanged", bindVoices);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", bindVoices);
  }, [selectSpeechVoice]);

  useEffect(() => {
    if (micState !== "processing" && processingLabelTimerRef.current) {
      clearInterval(processingLabelTimerRef.current);
      processingLabelTimerRef.current = null;
      setProcessingLabelIndex(0);
    }
    if (micState !== "processing") {
      clearProcessingFailSafe();
    }
  }, [micState]);

  useEffect(() => {
    if (!isHumanMode || stage !== "negotiating") return undefined;
    // Prevent restart if:
    // 1. TTS is speaking
    // 2. Mic is explicitly paused (user action)
    // 3. Mic is already starting (prevent startListening -> stopRecognition -> setMicState(inactive) -> loop)
    if (micState === "inactive" && !isTtsSpeakingRef.current && !micPausedRef.current && !isStartingRecognitionRef.current) {
      startListening();
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isHumanMode, stage, micState]);

  useEffect(() => {
    if (!isHumanMode || stage !== "negotiating") return undefined;
    const watchdog = setInterval(() => {
      if (liveModeNeedsTextFallback) return;
      if (document.visibilityState !== "visible") return;
      if (isTtsSpeakingRef.current || window.speechSynthesis?.speaking) return;
      if (micStateRef.current === "processing" || micStateRef.current === "locked") return;
      if (!recognitionRef.current && !isStartingRecognitionRef.current && !micPausedRef.current) {
        // eslint-disable-next-line no-console
        console.log("[MIC-DEBUG] Watchdog setting inactive (not paused)");
        setMicState("inactive");
      }
    }, 1200);
    return () => clearInterval(watchdog);
  }, [isHumanMode, stage, liveModeNeedsTextFallback]);

  const startNegotiation = async () => {
    const requestedMode = selectedPipeline;
    const requestedArchetype = selectedArchetype;
    setNegotiationMode(requestedMode);
    if (!authToken) {
      setShowAuthModal(true);
      setAuthError("");
      setPendingStart(true);
      setPendingMode(requestedMode);
      setPendingArchetype(requestedArchetype);
      return;
    }
    await beginNegotiation(authToken, requestedMode, requestedArchetype);
  };

  const beginNegotiation = async (tokenOverride, requestedMode = negotiationMode, requestedArchetype = selectedArchetype) => {
    const token = tokenOverride || authToken;
    if (!programUrl.trim()) {
      pushUiToast("Enter a valid program URL to continue.", "strategic");
      return;
    }
    if (isHumanDrivenPipeline(requestedMode)) {
      const permission = await ensureMicPermission();
      if (permission === "denied") {
        pushUiToast("Microphone unavailable. Live coaching will use text input fallback.", "strategic", 3800);
      }
    }
    setRunHistory([]);
    resetRun();
    setStage("analyzing");

    try {
      const analyzeRes = await fetch(`${BACKEND_URL}/analyze-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: programUrl.trim(), auth_token: token, archetype_id: requestedArchetype }),
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
      startWebsocketNegotiation(analyzeData.session_id, token, false, requestedMode, requestedArchetype);
    } catch (error) {
      pushUiToast(error.message || "Failed to start negotiation");
      setStage("idle");
    }
  };

  const startWebsocketNegotiation = (
    targetSessionId,
    token,
    retryMode = false,
    mode = negotiationMode,
    archetypeId = selectedArchetype
  ) => {
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
          mode,
          archetype_id: archetypeId,
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
      if (payload.type === "session_ready") {
        if (payload.data?.persona) setPersona(payload.data.persona);
        if (payload.data?.program) setProgram(payload.data.program);
        if (payload.data?.mode) setNegotiationMode(payload.data.mode);
      } else if (payload.type === "stream_chunk") {
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
        if (isHumanDrivenPipeline(mode) && normalized.agent === "counsellor") {
          clearProcessingFailSafe();
        }
        if (isHumanDrivenPipeline(mode) && normalized.agent === "student") {
          clearProcessingFailSafe();
          if (mode === "agent_powered_human_vs_ai") {
            setCopilotState("thinking");
          }
          setMicState("locked");
          speakStudentTurn(normalized.content, normalized.emotional_state);
        }
      } else if (payload.type === "copilot_update") {
        const data = payload.data || {};
        setCopilotData({
          analysis: String(data.analysis || "").trim(),
          suggestions: Array.isArray(data.suggestions) ? data.suggestions.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 3) : [],
          fact_check: String(data.fact_check || data.relevant_fact || "").trim(),
          round: Number(data.round || 0),
          updatedAt: Date.now(),
        });
        setCopilotState("ready");
        setCopilotPinnedSuggestion("");
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
        setMicState("inactive");
        stopRecognition();
        setShowReportDashboard(false);
        pushUiToast(`Conversation Completed\nDuration (mins) ${durationHms}`, "positive", 5200);
      } else if (payload.type === "warning") {
        clearProcessingFailSafe();
        pushUiToast(payload.data?.message || "Warning from server", "strategic", 3400);
      } else if (payload.type === "error") {
        clearProcessingFailSafe();
        // eslint-disable-next-line no-console
        console.error("Backend negotiation error", payload.data);
        pushUiToast(payload.data?.message || "Unexpected backend error");
        if (isHumanDrivenPipeline(mode)) {
          setMicState("inactive");
        }
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
      clearProcessingFailSafe();
      setMicState("inactive");
      stopRecognition();
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
        await beginNegotiation(data.token, pendingMode, pendingArchetype);
      } else if (pendingDownloadReport) {
        setPendingDownloadReport(false);
        await downloadReport(data.token);
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

  const closeArena = () => {
    setShowControlModal(false);
    setShowAuthModal(false);
    setPendingStart(false);
    setPendingDownloadReport(false);
    setExpandedContent(null);
    startNewSimulation();
  };

  const retrySimulation = () => {
    if (!sessionId || !authToken) {
      pushUiToast("Session missing. Start a new simulation.", "strategic");
      return;
    }
    resetRun();
    setStage("negotiating");
    setShowReportDashboard(false);
    startWebsocketNegotiation(sessionId, authToken, true, negotiationMode, selectedArchetype);
  };

  const downloadReport = async (tokenOverride = null) => {
    if (!sessionId || !analysis) return;
    const safeToken = typeof tokenOverride === "string" ? tokenOverride : "";
    const effectiveToken = safeToken || authToken;
    const res = await fetch(`${BACKEND_URL}/generate-report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        auth_token: effectiveToken,
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
      if (res.status === 401) {
        setPendingStart(false);
        setPendingDownloadReport(true);
        setShowAuthModal(true);
        setAuthError("Session expired. Re-authenticate to download report.");
        pushUiToast("Session expired. Please unlock again to download report.", "strategic", 3200);
        return;
      }
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
      <img className={`hero-bg ${!isTransparentStage ? "hero-bg-active" : ""}`} src={`${baseUrl}/negotiation.png`} alt="" aria-hidden="true" />
      <img className={`hero-bg ${isTransparentStage ? "hero-bg-active" : ""}`} src={`${baseUrl}/negotiation_transparent.png`} alt="" aria-hidden="true" />
      <div className="sceneOverlay" />

      {stage === "idle" && (
        <section className="hero launchHero">
          <button type="button" className="brandWordmarkBtn" onClick={closeArena} title="Close Arena">
            <h1 className="brandWordmark">
              <span className="brandClose">CLOSE</span>
              <span className="brandWire">WIRE</span>
            </h1>
          </button>
          <p className="subtitle">Simulate | Compete | Reflect</p>
          <div className="inputRow launchRow">
            <input
              type="url"
              value={programUrl}
              onChange={(e) => setProgramUrl(e.target.value)}
              placeholder="Enter Program URL here..."
            />
            <button className="launchBtn" onClick={startNegotiation}>Launch</button>
          </div>
        </section>
      )}

      {stage === "idle" && (
        <button
          type="button"
          className="commandDockBtn"
          style={{ position: "fixed", left: "12px", top: "12px", bottom: "auto", zIndex: 220 }}
          onClick={() => setShowControlModal((prev) => !prev)}
          title="Open pipeline and archetype selector"
        >
          &gt;_
        </button>
      )}

      <div className="uiToastStack">
        {uiToasts.map((toast) => (
          <div key={toast.id} className={`uiToast ${toast.tone}`}>
            {toast.text}
          </div>
        ))}
      </div>

      {stage === "negotiating" && isAgentPoweredMode && createPortal(
        <CopilotWidget
          visible
          state={copilotState}
          data={copilotData}
          pinnedSuggestion={copilotPinnedSuggestion}
          isHindi={String(persona?.archetype_id || "").toLowerCase() === "skeptical_shopper"}
          onApplySuggestion={handleApplyCopilotSuggestion}
          onExpand={() => setCopilotState(copilotData ? "ready" : "thinking")}
          onMinimize={() => setCopilotState("minimized")}
        />,
        document.body
      )}

      {showAuthModal && createPortal(
        <div className="authModalBackdrop">
          <form className="authModal" onSubmit={handlePasswordSubmit}>
            <button
              type="button"
              className="authCloseBtn"
              onClick={() => {
                setShowAuthModal(false);
                setPendingStart(false);
                setPendingDownloadReport(false);
                setPendingMode("ai_vs_ai");
                setPendingArchetype("desperate_switcher");
              }}
              aria-label="Close authentication modal"
              title="Close"
            >
              X
            </button>
            <h3>Classified Access</h3>
            <p>Authenticate to unlock this arena.</p>
            <input
              type="password"
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              placeholder="Password"
              autoFocus
            />
            {authError && <div className="authError">{authError}</div>}
            <div className="authActions">
              <button type="submit" className="authUnlockBtn">Unlock</button>
            </div>
          </form>
        </div>,
        document.body
      )}

      {showControlModal && stage === "idle" && (
        <div
          className="controlModalBackdrop"
          style={{ position: "fixed", inset: 0, zIndex: 218 }}
          onClick={() => setShowControlModal(false)}
        >
          <section
            className="controlModalCard"
            style={{ position: "fixed", left: 0, top: 0, bottom: 0, zIndex: 219 }}
            onClick={(event) => event.stopPropagation()}
          >
            <header>
              <h3>Arenas</h3>
              <button type="button" onClick={() => setShowControlModal(false)} aria-label="Close control panel">X</button>
            </header>
            <section className="controlSection pipelineSection">
              <h4 className="controlSectionTitle">
                <span className="sectionIcon" aria-hidden="true">
                  <svg viewBox="0 0 16 16" focusable="false" aria-hidden="true">
                    <rect x="2" y="3" width="12" height="3" rx="1.5" />
                    <rect x="2" y="10" width="12" height="3" rx="1.5" />
                  </svg>
                </span>
                Pipeline
              </h4>
              <div className="pipelineSegments">
                {PIPELINE_OPTIONS.map((pipeline) => {
                  const isComingSoon = pipeline.status === "coming_soon";
                  return (
                    <button
                      key={pipeline.id}
                      type="button"
                      className={`pipelineSegment ${selectedPipeline === pipeline.id ? "selected" : ""} ${isComingSoon ? "comingSoon" : ""}`}
                      onClick={() => {
                        if (!isComingSoon) setSelectedPipeline(pipeline.id);
                      }}
                      disabled={isComingSoon}
                    >
                      <strong>{pipeline.title}</strong>
                      <span>{pipeline.subtitle}</span>
                      {isComingSoon && (
                        <em className="pipelineLock" aria-hidden="true">
                          <svg viewBox="0 0 16 16" focusable="false">
                            <path d="M4 7V5a4 4 0 1 1 8 0v2h1a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h1Zm2 0h4V5a2 2 0 1 0-4 0v2Z" />
                          </svg>
                        </em>
                      )}
                    </button>
                  );
                })}
              </div>
            </section>
            <div className="controlSplitBar" />
            <section className="controlSection archetypeSection">
              <h4 className="controlSectionTitle">
                <span className="sectionIcon" aria-hidden="true">
                  <svg viewBox="0 0 16 16" focusable="false" aria-hidden="true">
                    <circle cx="8" cy="5" r="3" />
                    <path d="M2 14a6 6 0 1 1 12 0H2Z" />
                  </svg>
                </span>
                Prospect Archetype
              </h4>
              <div className="archetypeGrid">
                {ARCHETYPE_CARDS.map((card) => (
                  <button
                    key={card.id}
                    type="button"
                    className={`archetypeCard ${selectedArchetype === card.id ? "selected" : ""}`}
                    style={{ "--archetype-accent": card.accent }}
                    onClick={() => setSelectedArchetype(card.id)}
                  >
                    <span className="archetypeIcon">{card.icon}</span>
                    <strong>{card.title}</strong>
                    <p>{card.profile}</p>
                  </button>
                ))}
              </div>
            </section>
          </section>
        </div>
      )}

      {stage === "analyzing" && (
        <section className="activationOverlay">
          <div className="activationContent">
            <button type="button" className="brandWordmarkBtn" onClick={closeArena} title="Close Arena">
              <h1 className="brandWordmark">
                <span className="brandClose">CLOSE</span>
                <span className="brandWire">WIRE</span>
              </h1>
            </button>
            <p className="subtitle">Simulate | Compete | Reflect</p>
            <h2>{activationTitle}</h2>
            <div className="activationSteps">
              {activationSteps.map((step, index) => (
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
            <h2>{activationTitle}</h2>
            <div className="activationSteps">
              {activationSteps.map((step, index) => (
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
          {isHumanMode && (
            <div className="arenaBrandMark">
              <button type="button" className="brandWordmarkBtn brandWordmarkBtnSm" onClick={closeArena} title="Close Arena">
                <span className="brandWordmark brandWordmarkSm">
                  <span className="brandClose">CLOSE</span>
                  <span className="brandWire">WIRE</span>
                </span>
              </button>
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
            </div>
          )}
          {stage === "completed" && !showReportDashboard && (
            <div className="arenaBottomActions">
              <button className="ghostBtn viewReportBtn" onClick={() => setShowReportDashboard(true)}>
                View Report
              </button>
            </div>
          )}
          <div className={`arenaTopZone ${isHumanMode ? "human-mode" : ""}`}>
            {!isHumanMode && (
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
            )}
            <div className="agentLayer">
              {!isHumanMode && (
                <article className={`agentIdentity counsellor ${momentumValue > 65 ? "glow" : ""}`}>
                  <h3>Program Counseller</h3>
                  <p>{`${counsellorName || "Admissions Counsellor"}, ${program?.program_name || "Program"}`}</p>
                </article>
              )}
              {!isHumanMode && (
                <article className={`agentIdentity student ${momentumValue < 40 ? "glow" : ""}`}>
                  <h3>Prospective Student</h3>
                  <p>{`${persona?.name || "Student"}, ${formatArchetype(persona)}`}</p>
                </article>
              )}
            </div>
            
            {isHumanMode && (
              <div className={`liveAiPanel ${micState === "locked" ? "speaking" : ""}`}>
                <img
                  className="studentAvatar"
                  src={studentImageSrc}
                  alt={`${persona?.name || "Student"} profile`}
                  onError={() => {
                    const base = process.env.PUBLIC_URL || "";
                    setStudentImageSrc(`${base}/student-placeholder.svg`);
                  }}
                />
                <article className="studentMiniCard">
                  <strong>Prospective Student</strong>
                  <p>{`${persona?.name || "Student"}, ${formatArchetype(persona)}`}</p>
                  <span>{micState === "locked" ? "Speaking..." : "Waiting..."}</span>
                </article>
              </div>
            )}


          </div>

          <div className="arenaMainContent">
            {isHumanMode && stage === "negotiating" && (
              <aside className="arenaSidebar">
                <section className="liveCoachPanel">
                  <div className={`liveMicPanel state-${micState}`}>
                    <div className="liveMicHeader">
                      <article className="counsellorIdentityCompact">
                        <strong>Your Turn (Counsellor)</strong>
                        <p>{counsellorName || "Admissions Counsellor"}, {program?.program_name || "Program"}</p>
                      </article>
                      <div className="liveMicHeaderActions">
                        {/* Visual Mic Indicator (Not a button) */}
                        <div className={`micStatusIndicator ${micState === "listening" ? "active" : "inactive"}`} style={{ marginRight: "8px" }}>
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                            <line x1="12" y1="19" x2="12" y2="23" />
                            <line x1="8" y1="23" x2="16" y2="23" />
                          </svg>
                        </div>

                        {/* Pause/Resume Button */}
                        <button
                          type="button"
                          className={`pauseAutoSendBtn ${isAutoSendEnabled ? "auto-on" : "auto-off"}`}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            const nextState = !isAutoSendEnabled;
                            // eslint-disable-next-line no-console
                            console.log("[MIC-DEBUG] Pause button clicked. Current isAutoSendEnabled:", isAutoSendEnabled, "Next:", nextState);
                            
                            setIsAutoSendEnabled(nextState);
                            micPausedRef.current = !nextState;

                            if (nextState) {
                              micPausedRef.current = false;
                              // eslint-disable-next-line no-console
                              console.log("[MIC-DEBUG] Resuming mic (User Action)");
                              startListening();
                            } else {
                              micPausedRef.current = true;
                              // eslint-disable-next-line no-console
                              console.log("[MIC-DEBUG] Pausing mic (User Action)");
                              stopRecognition();
                            }
                          }}
                          title={isAutoSendEnabled ? "Pause Auto-Send & Mic" : "Resume Auto-Send & Mic"}
                        >
                          {isAutoSendEnabled ? (
                            // Pause Icon
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <rect x="6" y="4" width="4" height="16" />
                              <rect x="14" y="4" width="4" height="16" />
                            </svg>
                          ) : (
                            // Play Icon
                             <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <polygon points="5 3 19 12 5 21 5 3" />
                            </svg>
                          )}
                        </button>
                      </div>
                    </div>

                    {micState === "listening" && (
                    <div className="micActiveGlowBar" style={{ "--mic-intensity": waveformLevel }} />
                    )}
                  <textarea
                    ref={humanInputRef}
                    className="humanInputArea"
                    value={liveModeNeedsTextFallback ? humanInputText : liveTranscript}
                    onChange={(event) => {
                      setHumanInputText(event.target.value);
                      setLiveTranscript(event.target.value);
                      liveTranscriptRef.current = event.target.value;
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        if (micState === "locked" || micState === "processing") return;
                        sendHumanInput(liveModeNeedsTextFallback ? humanInputText : liveTranscriptRef.current);
                      }
                    }}
                    placeholder={liveModeNeedsTextFallback
                      ? "Type your response and press Enter..."
                      : "Listening... (Press Enter to force send)"}
                    disabled={micState === "locked"}
                  />
                  </div>
                </section>
              </aside>
            )}

            <div className={`projectionLane ${isHumanMode ? "human-mode-projection" : ""}`} ref={projectionRef}>
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
                  <details className="internalThoughtDetails">
                    <summary>Internal Thought</summary>
                    <div>{msg.internal_thought}</div>
                  </details>
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
            <div className="reportBrandMark">
              <button type="button" className="brandWordmarkBtn brandWordmarkBtnSm" onClick={closeArena} title="Close Arena">
                <span className="brandWordmark brandWordmarkSm">
                  <span className="brandClose">CLOSE</span>
                  <span className="brandWire">WIRE</span>
                </span>
              </button>
            </div>
            <div className="resultScrollBody">
              <header className="outcomeSummaryCard">
                <h2>{outcomeHeadline}</h2>
                <h3>Final Score: {analysis?.judge?.negotiation_score ?? 0} / 100</h3>
                <p>{analysis?.judge?.why || "Simulation completed."}</p>
                <div className="finalMetricChips">
                  <span className={`metricChip commitmentChip ${chipStateClass(commitmentReportState(analysis?.judge?.commitment_signal))}`}>
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
                        {retryPerformance.latest.deltaFromPrevious >= 0 ? "Up" : "Down"} {retryPerformance.latest.deltaFromPrevious >= 0 ? "+" : ""}
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
              <button className="downloadBtn" onClick={() => downloadReport()}>
                Download Report
              </button>
              <button className={`ghostBtn ${showRestartPulse ? "pulse" : ""}`} onClick={retrySimulation}>
                Rematch. Self-Corrected.
              </button>
              <button className="ghostBtn" onClick={startNewSimulation}>
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

import React, { useMemo } from "react";
import Draggable from "react-draggable";

function CopilotWidget({
  visible,
  state,
  data,
  pinnedSuggestion,
  onApplySuggestion,
  onExpand,
  onMinimize,
}) {
  const suggestions = useMemo(() => {
    const list = Array.isArray(data?.suggestions) ? data.suggestions : [];
    return list.filter(Boolean).slice(0, 3);
  }, [data]);

  if (!visible) return null;

  const showCard = state === "ready";
  const showThinking = state === "thinking";

  return (
    <Draggable bounds="body" handle=".copilotDragHandle">
      <div className={`copilotWidget ${showCard ? "expanded" : "collapsed"}`}>
        {showCard ? (
          <section className="copilotCard">
            <header className="copilotDragHandle">
              <strong>Cortex Copilot</strong>
              <button type="button" onClick={onMinimize} aria-label="Minimize copilot">
                -
              </button>
            </header>
            <p className="copilotAnalysis">{data?.analysis || "Analyzing last student response..."}</p>
            <div className="copilotSuggestionRow">
              {suggestions.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`copilotSuggestionChip ${pinnedSuggestion === item ? "pinned" : ""}`}
                  onClick={() => onApplySuggestion(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            {data?.fact_check && (
              <div className="copilotFact">
                <span>Fact Check</span>
                <p>{data.fact_check}</p>
              </div>
            )}
          </section>
        ) : (
          <button
            type="button"
            className={`copilotOrb ${showThinking ? "thinking" : ""}`}
            onClick={onExpand}
            aria-label="Open copilot"
          >
            <span>{showThinking ? "..." : "AI"}</span>
          </button>
        )}
      </div>
    </Draggable>
  );
}

export default CopilotWidget;

import React, { useMemo, useState } from "react";
import Draggable from "react-draggable";

const CopilotWidget = function CopilotWidget({
  visible,
  state,
  data,
  history = [],
  pinnedSuggestion,
  isHindi = false,
  onApplySuggestion,
  onExpand,
  onMinimize,
}) {
  const [expandedSuggestionId, setExpandedSuggestionId] = useState(null);
  const [expandedHistorySet, setExpandedHistorySet] = useState(new Set());

  const toggleHistoryItem = (id) => {
    setExpandedHistorySet(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const historyItems = useMemo(() => {
    if (!history || history.length === 0) return [];
    return history.filter(item => item && (item.analysis || (item.suggestions && item.suggestions.length > 0)));
  }, [history]);

  // Current major suggestions (only used if history is empty or for fallback)
  const currentSuggestions = useMemo(() => {
    const list = Array.isArray(data?.suggestions) ? data.suggestions : [];
    return list.slice(0, 3);
  }, [data]);

  if (!visible) return null;

  const showCard = state === "ready" || state === "thinking";
  const showThinking = state === "thinking";
  
  const heading = isHindi ? "कॉर्टेक्स कोपायलट" : "Cortex Copilot";
  const thinkingLabel = isHindi ? "विश्लेषण जारी..." : "Analyzing last student response...";
  const factLabel = isHindi ? "तथ्य जाँच" : "Fact Check";

  // Helper to generate a unique key for accordion state
  const getSuggestionKey = (contextId, index) => {
    return `${contextId}-${index}`;
  };

  const handleSuggestionClick = (item, index, contextId) => {
    const isObject = typeof item === "object" && item !== null;
    if (isObject) {
       // Toggle expansion
       const key = getSuggestionKey(contextId, index);
       setExpandedSuggestionId(prev => (prev === key ? null : key));
    } else {
       // Legacy string behavior: apply immediately
       onApplySuggestion(item);
    }
  };

  const renderSuggestionList = (list, contextId) => {
    if (!list || list.length === 0) return null;
    
    return (
      <div className="copilotSuggestionRow">
        {list.map((item, idx) => {
          const isObject = typeof item === "object" && item !== null;
          const title = isObject ? item.title : item;
          const description = isObject ? item.description : item;
          const key = getSuggestionKey(contextId, idx);
          const isExpanded = expandedSuggestionId === key;
          
          // Check pinned state against the content that gets applied (description)
          const isPinned = pinnedSuggestion === description;

          return (
            <div key={idx} className="copilotSuggestionWrapper">
              <button
                type="button"
                className={`copilotSuggestionChip ${isPinned ? "pinned" : ""}`}
                onClick={() => handleSuggestionClick(item, idx, contextId)}
              >
                {title}
              </button>
              {isObject && isExpanded && (
                <div 
                  className="copilotSuggestionDetail" 
                  onClick={() => onApplySuggestion(description)}
                  title="Click to apply"
                >
                  {description}
                  <span className="copilotApplyHint">Click text to Apply</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <Draggable bounds="body" handle=".copilotDragHandle">
      <div className={`copilotWidget ${showCard ? "expanded" : "collapsed"}`}>
        {showCard ? (
          <section className="copilotCard">
            <header className="copilotDragHandle">
              <strong>{heading}</strong>
              <div className="copilotControls">
                  <span className="copilotHistoryCount" title="History count">
                    {historyItems.length > 0 ? historyItems.length : ""}
                  </span>
                  <button type="button" onClick={onMinimize} aria-label="Minimize copilot">
                    -
                  </button>
              </div>
            </header>
            
            <div className="copilotScrollArea">
              {/* Render History Items (Oldest First) */}
              {[...historyItems].reverse().map((item, originalIndex, arr) => {
                const isLatest = originalIndex === arr.length - 1;
                const index = arr.length - 1 - originalIndex; // Keep index consistent with data map
                const itemId = item.updatedAt || index;
                // Latest is always treated as expanded for display. Older ones check the set.
                const isExpanded = isLatest || expandedHistorySet.has(itemId);
                const itemSuggestions = Array.isArray(item.suggestions) ? item.suggestions.slice(0, 3) : [];

                return (
                  <div key={itemId} className={`copilotItem ${isLatest ? "latest" : "history"} ${isExpanded ? "expanded" : "collapsed"}`}>
                     {item.round > 0 && (
                      <div 
                        className={`copilotRoundLabel ${!isLatest ? "clickable" : ""}`}
                        onClick={() => !isLatest && toggleHistoryItem(itemId)}
                        title={!isLatest ? "Click to toggle" : ""}
                      >
                        Round {item.round}
                        {!isLatest && <span className="toggle-icon">{isExpanded ? " ▼" : " ▶"}</span>}
                      </div>
                    )}
                    
                    {isExpanded && (
                      <>
                        <p className="copilotAnalysis">{item.analysis}</p>
                        {renderSuggestionList(itemSuggestions, `hist-${index}`)}
                        {item.fact_check && (
                          <div className="copilotFact">
                            <span>{factLabel}</span>
                            <p>{item.fact_check}</p>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}

              {/* If history is empty, show the current data state manually */}
              {!showThinking && historyItems.length === 0 && (
                 <div className="copilotItem latest">
                    <p className="copilotAnalysis">
                        {data?.analysis}
                    </p>
                    {renderSuggestionList(currentSuggestions, "current")}
                    {data?.fact_check && (
                      <div className="copilotFact">
                        <span>{factLabel}</span>
                        <p>{data.fact_check}</p>
                      </div>
                    )}
                 </div>
              )}

              {showThinking && (
                <div className="copilotItem latest">
                  <p className="copilotAnalysis">{thinkingLabel}</p>
                </div>
              )}
            </div>
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
};

export default React.memo(CopilotWidget);

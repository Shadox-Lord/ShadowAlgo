import { useState, useRef, useEffect } from "react";

// Comment at top of file updated - see line 4
// Dependencies: npm install openai

function TypingIndicator() {
  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", padding: "10px 0" }}>
      {[0, 1, 2].map(i => (
        <div key={i} style={{
          width: 7, height: 7, borderRadius: "50%",
          background: "var(--color-text-tertiary)",
          animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
        }} />
      ))}
      <style>{`@keyframes pulse { 0%,100%{opacity:.3;transform:scale(1)} 50%{opacity:1;transform:scale(1.3)} }`}</style>
    </div>
  );
}

function ScoreBadge({ score, label }) {
  const color = score >= 8 ? "#639922" : score >= 6 ? "#185FA5" : score >= 4 ? "#BA7517" : "#A32D2D";
  const bg = score >= 8 ? "#EAF3DE" : score >= 6 ? "#E6F1FB" : score >= 4 ? "#FAEEDA" : "#FCEBEB";
  return (
    <span style={{
      background: bg, color, fontWeight: 500, fontSize: 12,
      padding: "2px 8px", borderRadius: 100, border: `0.5px solid ${color}40`
    }}>{score}/10 {label}</span>
  );
}

function renderMarkdown(text) {
  const lines = text.split("\n");
  const elements = [];
  let key = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("## ")) {
      elements.push(
        <h3 key={key++} style={{
          fontSize: 15, fontWeight: 500, color: "var(--color-text-primary)",
          margin: "1.5rem 0 0.5rem", paddingBottom: 6,
          borderBottom: "0.5px solid var(--color-border-tertiary)"
        }}>{line.slice(3)}</h3>
      );
    } else if (line.startsWith("### ")) {
      elements.push(
        <h4 key={key++} style={{
          fontSize: 13, fontWeight: 500, color: "var(--color-text-secondary)",
          margin: "1rem 0 0.25rem"
        }}>{line.slice(4)}</h4>
      );
    } else if (line.startsWith("**") && line.endsWith("**")) {
      elements.push(
        <p key={key++} style={{ fontWeight: 500, fontSize: 13, margin: "0.5rem 0 0.1rem", color: "var(--color-text-primary)" }}>
          {line.slice(2, -2)}
        </p>
      );
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      const content = line.slice(2).replace(/\*\*(.*?)\*\*/g, (_, m) => `<strong>${m}</strong>`);
      elements.push(
        <div key={key++} style={{ display: "flex", gap: 8, margin: "2px 0" }}>
          <span style={{ color: "var(--color-text-tertiary)", fontSize: 13, flexShrink: 0, marginTop: 2 }}>—</span>
          <span style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}
            dangerouslySetInnerHTML={{ __html: content }} />
        </div>
      );
    } else if (line.match(/^\d+\. /)) {
      const [num, ...rest] = line.split(". ");
      const content = rest.join(". ").replace(/\*\*(.*?)\*\*/g, (_, m) => `<strong>${m}</strong>`);
      elements.push(
        <div key={key++} style={{ display: "flex", gap: 8, margin: "3px 0" }}>
          <span style={{ color: "var(--color-text-tertiary)", fontSize: 13, flexShrink: 0, fontWeight: 500 }}>{num}.</span>
          <span style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}
            dangerouslySetInnerHTML={{ __html: content }} />
        </div>
      );
    } else if (line.trim() === "") {
      elements.push(<div key={key++} style={{ height: 6 }} />);
    } else {
      const content = line.replace(/\*\*(.*?)\*\*/g, (_, m) => `<strong>${m}</strong>`);
      elements.push(
        <p key={key++} style={{ fontSize: 13, color: "var(--color-text-secondary)", margin: "2px 0", lineHeight: 1.7 }}
          dangerouslySetInnerHTML={{ __html: content }} />
      );
    }
  }
  return elements;
}

function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{
      display: "flex", flexDirection: "column",
      alignItems: isUser ? "flex-end" : "flex-start",
      marginBottom: 16
    }}>
      {!isUser && (
        <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 4, fontWeight: 500 }}>
          AUDITOR
        </span>
      )}
      <div style={{
        maxWidth: isUser ? "75%" : "100%",
        background: isUser ? "var(--color-background-info)" : "var(--color-background-secondary)",
        borderRadius: isUser ? "12px 12px 4px 12px" : "4px 12px 12px 12px",
        padding: isUser ? "8px 12px" : "10px 14px",
        border: "0.5px solid var(--color-border-tertiary)"
      }}>
        {isUser ? (
          <p style={{ fontSize: 13, margin: 0, color: "var(--color-text-info)" }}>{msg.content}</p>
        ) : (
          <div>{renderMarkdown(msg.content)}</div>
        )}
      </div>
    </div>
  );
}

const QUICK_QUESTIONS = [
  "Run the full system audit",
  "Which agent is most likely to hallucinate?",
  "Is this system ready for a $10k funded account?",
  "What's the cheapest way to deploy this on Vercel?",
  "Should I use Claude or GPT-4o for the debate agents?",
  "What's the single biggest risk to my prop firm evaluation?",
];

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const sendMessage = async (text) => {
    const userText = text || input.trim();
    if (!userText || loading) return;
    setInput("");
    setError(null);

    const newMessages = [...messages, { role: "user", content: userText }];
    setMessages(newMessages);
    setLoading(true);

    try {
      // Call secure serverless API with real-time market data integration
      const res = await fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: "BTCUSDT",
          accountBalance: 10000,
          riskPreference: "moderate"
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.details || errorData.error || errorData.message || `API error ${res.status}`);
      }
      
      const data = await res.json();
      
      // Format the AI response for display
      const analysis = data.analysis;
      let reply = `**${analysis.decision}** (${analysis.confidence}% confidence)\n\n`;
      reply += `${analysis.reasoning}\n\n`;
      
      if (analysis.decision !== 'NO_TRADE') {
        reply += `**Entry:** $${analysis.entry_price}\n`;
        reply += `**Stop Loss:** $${analysis.stop_loss}\n`;
        reply += `**Take Profit:** $${analysis.take_profit}\n\n`;
        
        if (data.riskMetrics) {
          reply += `**Position Size:** ${data.riskMetrics.positionSize} units\n`;
          reply += `**Risk Amount:** $${data.riskMetrics.riskAmount}\n`;
          reply += `**Potential Profit:** $${data.riskMetrics.potentialProfit}\n`;
          reply += `**Risk:Reward:** 1:${data.riskMetrics.rrRatio}\n`;
        }
      }
      
      reply += `\n**Invalidation:** ${analysis.invalidation_condition}\n`;
      reply += `\n*Risk Score: ${analysis.risk_score}/10*`;

      setMessages(prev => [...prev, { role: "assistant", content: reply }]);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const hasMessages = messages.length > 0;

  return (
    <div style={{ padding: "1rem 0", fontFamily: "var(--font-sans)" }}>
      <h2 className="sr-only">Shadow AI Trading System Auditor</h2>

      <div style={{
        background: "var(--color-background-primary)",
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: "var(--border-radius-lg)",
        overflow: "hidden"
      }}>
        <div style={{
          padding: "14px 16px 12px",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          display: "flex", alignItems: "center", justifyContent: "space-between"
        }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>
              Shadow AI Trading System — Auditor
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>
              ruthless systems review · EURUSD · prop firm survival
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <ScoreBadge score={8.7} label="architecture" />
            <ScoreBadge score={4.5} label="live safety" />
          </div>
        </div>

        <div style={{ padding: "16px", minHeight: 300, maxHeight: 520, overflowY: "auto" }}>
          {!hasMessages && (
            <div style={{ marginBottom: 20 }}>
              <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 14, lineHeight: 1.6 }}>
                I've read the full analysis report, the shadow blueprint, and the system prompt. Ask me anything about this system — or run the complete audit.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8 }}>
                {QUICK_QUESTIONS.map(q => (
                  <button key={q} onClick={() => sendMessage(q)} style={{
                    textAlign: "left", padding: "8px 12px", fontSize: 12,
                    color: "var(--color-text-secondary)", cursor: "pointer",
                    border: "0.5px solid var(--color-border-tertiary)",
                    borderRadius: "var(--border-radius-md)",
                    background: "var(--color-background-secondary)",
                    lineHeight: 1.4, transition: "background 0.15s"
                  }}
                  onMouseEnter={e => e.target.style.background = "var(--color-background-tertiary)"}
                  onMouseLeave={e => e.target.style.background = "var(--color-background-secondary)"}
                  >{q} ↗</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => <Message key={i} msg={m} />)}
          {loading && (
            <div style={{ alignItems: "flex-start" }}>
              <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", fontWeight: 500 }}>AUDITOR</span>
              <div style={{
                background: "var(--color-background-secondary)",
                borderRadius: "4px 12px 12px 12px",
                padding: "8px 14px",
                border: "0.5px solid var(--color-border-tertiary)",
                display: "inline-block"
              }}>
                <TypingIndicator />
              </div>
            </div>
          )}
          {error && (
            <div style={{
              background: "var(--color-background-danger)", color: "var(--color-text-danger)",
              fontSize: 12, padding: "8px 12px", borderRadius: "var(--border-radius-md)",
              border: "0.5px solid var(--color-border-danger)", marginTop: 8
            }}>Error: {error}</div>
          )}
          <div ref={bottomRef} />
        </div>

        <div style={{
          borderTop: "0.5px solid var(--color-border-tertiary)",
          padding: "12px 16px",
          display: "flex", gap: 8
        }}>
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !e.shiftKey && sendMessage()}
            placeholder="Ask the auditor..."
            disabled={loading}
            style={{ flex: 1, fontSize: 13 }}
          />
          <button
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
            style={{ padding: "0 16px", fontSize: 13, cursor: loading ? "not-allowed" : "pointer" }}
          >
            {loading ? "..." : "Send ↗"}
          </button>
        </div>
      </div>

      <div style={{
        marginTop: 10, display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap"
      }}>
        <button onClick={() => { setMessages([]); setError(null); }} style={{
          fontSize: 11, color: "var(--color-text-tertiary)", background: "none",
          border: "none", cursor: "pointer", padding: "4px 8px"
        }}>clear chat</button>
        <button onClick={() => sendMessage("Perform the complete ruthless audit of the Shadow AI Trading System. Follow the exact 4-section format. Be specific, blunt, and final. No alternatives, no maybes. This is the system's fate.")} disabled={loading} style={{
          fontSize: 11, padding: "4px 10px", cursor: "pointer",
          border: "0.5px solid var(--color-border-secondary)",
          borderRadius: "var(--border-radius-md)",
          background: "var(--color-background-secondary)",
          color: "var(--color-text-secondary)"
        }}>run full audit ↗</button>
      </div>
    </div>
  );
}

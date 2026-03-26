import React, { useState, useEffect, useRef, useCallback } from "react";

// ============================================================================
// CONFIG
// ============================================================================
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Node type → color mapping (SAP-inspired palette)
const NODE_COLORS = {
  Customer: "#2563eb",      // Blue
  SalesOrder: "#7c3aed",    // Purple
  Delivery: "#059669",      // Green
  BillingDocument: "#d97706",// Amber
  JournalEntry: "#dc2626",  // Red
  Payment: "#0891b2",       // Cyan
  Product: "#c026d3",       // Fuchsia
  Plant: "#65a30d",         // Lime
};

const NODE_SHAPES = {
  Customer: "ellipse",
  SalesOrder: "round-rectangle",
  Delivery: "round-rectangle",
  BillingDocument: "round-rectangle",
  JournalEntry: "diamond",
  Payment: "diamond",
  Product: "hexagon",
  Plant: "triangle",
};

// ============================================================================
// GRAPH VIEW COMPONENT (Cytoscape.js)
// ============================================================================
function GraphView({ onNodeSelect, selectedNodes, searchHighlight }) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [filterType, setFilterType] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [searchResults, setSearchResults] = useState([]);

  // Load Cytoscape library dynamically
  useEffect(() => {
    const loadCytoscape = async () => {
      if (window.cytoscape) return window.cytoscape;
      return new Promise((resolve) => {
        const script = document.createElement("script");
        script.src = "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js";
        script.onload = () => resolve(window.cytoscape);
        document.head.appendChild(script);
      });
    };

    const init = async () => {
      const cytoscape = await loadCytoscape();

      // Fetch graph data
      const url = filterType
        ? `${API_BASE}/api/graph?node_type=${filterType}`
        : `${API_BASE}/api/graph`;

      const [graphRes, statsRes] = await Promise.all([
        fetch(url),
        fetch(`${API_BASE}/api/graph/stats`),
      ]);

      const graphData = await graphRes.json();
      const statsData = await statsRes.json();
      setStats(statsData);

      // Initialize Cytoscape
      if (cyRef.current) cyRef.current.destroy();

      cyRef.current = cytoscape({
        container: containerRef.current,
        elements: [...graphData.nodes, ...graphData.edges],
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              "font-size": "8px",
              "font-family": "sans-serif",
              "text-wrap": "ellipsis",
              "text-max-width": "80px",
              "text-valign": "bottom",
              "text-margin-y": 4,
              color: "#e2e8f0",
              "background-color": function(ele) { return NODE_COLORS[ele.data("type")] || "#6b7280"; },
              shape: function(ele) { return NODE_SHAPES[ele.data("type")] || "ellipse"; },
              width: 20,
              height: 20,
              "border-width": 1,
              "border-color": "#1e293b",
              "overlay-opacity": 0,
            },
          },
          {
            selector: "node:selected",
            style: {
              "border-width": 3,
              "border-color": "#f8fafc",
              width: 30,
              height: 30,
              "font-weight": "bold",
              "font-size": "10px",
            },
          },
          {
            selector: "node.highlighted",
            style: {
              "border-width": 3,
              "border-color": "#fbbf24",
              width: 30,
              height: 30,
              "background-opacity": 1,
              "z-index": 999,
              "font-size": "10px",
              label: "data(label)",
            },
          },
          {
            selector: "node.dimmed",
            style: {
              opacity: 0.15,
              label: "",
            },
          },
          {
            selector: "edge",
            style: {
              width: 1,
              "line-color": "#334155",
              "target-arrow-color": "#334155",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              "arrow-scale": 0.6,
              opacity: 0.4,
            },
          },
          {
            selector: "edge.highlighted",
            style: {
              "line-color": "#fbbf24",
              "target-arrow-color": "#fbbf24",
              width: 2,
              opacity: 1,
              "z-index": 999,
            },
          },
          {
            selector: "edge.dimmed",
            style: {
              opacity: 0.05,
            },
          },
        ],
        layout: {
          name: "concentric",
          fit: true,
          padding: 30,
          minNodeSpacing: 15,
          concentric: function(node) {
            var typeOrder = {Customer: 6, SalesOrder: 5, Delivery: 4, BillingDocument: 3, JournalEntry: 2, Payment: 1, Product: 0, Plant: 0};
            return typeOrder[node.data("type")] || 0;
          },
          levelWidth: function() { return 2; },
        },
        minZoom: 0.05,
        maxZoom: 5,
        wheelSensitivity: 0.3,
      });

      // Click handler for nodes
      cyRef.current.on("tap", "node", function(evt) {
        var node = evt.target;
        var data = node.data();
        onNodeSelect(data);
      });

      // Double-click to zoom into neighborhood
      cyRef.current.on("dbltap", "node", function(evt) {
        var node = evt.target;
        var neighborhood = node.neighborhood().add(node);
        cyRef.current.animate({
          fit: { eles: neighborhood, padding: 50 }
        }, { duration: 400 });
      });

      setLoading(false);
    };

    init().catch(console.error);
  }, [filterType]);

  // Highlight nodes from search/query results
  useEffect(() => {
    if (!cyRef.current || !searchHighlight?.length) return;
    cyRef.current.elements().removeClass("highlighted dimmed");

    const ids = new Set(searchHighlight);
    cyRef.current.nodes().forEach(function(node) {
      if (ids.has(node.data("id"))) {
        node.addClass("highlighted");
      } else {
        node.addClass("dimmed");
      }
    });
    cyRef.current.edges().forEach(function(edge) {
      if (ids.has(edge.data("source")) && ids.has(edge.data("target"))) {
        edge.addClass("highlighted");
      } else {
        edge.addClass("dimmed");
      }
    });

    // Zoom to highlighted nodes
    var highlighted = cyRef.current.nodes(".highlighted");
    if (highlighted.length > 0 && highlighted.length < 50) {
      cyRef.current.animate({
        fit: { eles: highlighted, padding: 60 }
      }, { duration: 400 });
    }
  }, [searchHighlight]);

  // Node search
  const handleSearch = async (term) => {
    setSearchTerm(term);
    if (term.length < 2) {
      setSearchResults([]);
      if (cyRef.current) cyRef.current.elements().removeClass("highlighted dimmed");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/graph/search?q=${encodeURIComponent(term)}`);
      const data = await res.json();
      setSearchResults(data.results || []);
    } catch (e) {
      console.error(e);
    }
  };

  const focusNode = (nodeId) => {
    if (!cyRef.current) return;
    const node = cyRef.current.getElementById(nodeId);
    if (node.length) {
      cyRef.current.animate({ center: { eles: node }, zoom: 2.5 }, { duration: 400 });
      cyRef.current.elements().removeClass("highlighted dimmed");
      node.addClass("highlighted");
      node.neighborhood().addClass("highlighted");
      cyRef.current.elements().not(node.neighborhood().add(node)).addClass("dimmed");
      onNodeSelect(node.data());
    }
    setSearchResults([]);
    setSearchTerm("");
  };

  return (
    <div className="graph-panel">
      {/* Toolbar */}
      <div className="graph-toolbar">
        <div className="search-box">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <input
            type="text"
            placeholder="Search nodes..."
            value={searchTerm}
            onChange={(e) => handleSearch(e.target.value)}
          />
          {searchResults.length > 0 && (
            <div className="search-dropdown">
              {searchResults.map((r) => (
                <div key={r.id} className="search-result" onClick={() => focusNode(r.id)}>
                  <span className="type-badge" style={{ background: NODE_COLORS[r.type] }}>
                    {r.type}
                  </span>
                  <span>{r.label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="filter-pills">
          <button
            className={`pill ${!filterType ? "active" : ""}`}
            onClick={() => { setFilterType(null); }}
          >
            All
          </button>
          {Object.keys(NODE_COLORS).map((type) => (
            <button
              key={type}
              className={`pill ${filterType === type ? "active" : ""}`}
              style={{ "--pill-color": NODE_COLORS[type] }}
              onClick={() => setFilterType(filterType === type ? null : type)}
            >
              {type}
            </button>
          ))}
        </div>
        <button
          className="reset-btn"
          onClick={() => {
            if (cyRef.current) {
              cyRef.current.elements().removeClass("highlighted dimmed");
              cyRef.current.fit(null, 30);
            }
          }}
        >
          Reset View
        </button>
      </div>

      {/* Graph Container */}
      <div ref={containerRef} className="graph-container">
        {loading && (
          <div className="loading-overlay">
            <div className="spinner" />
            <p>Loading graph...</p>
          </div>
        )}
      </div>

      {/* Stats bar */}
      {stats && (
        <div className="stats-bar">
          <span>{stats.total_nodes} nodes</span>
          <span className="divider">·</span>
          <span>{stats.total_edges} edges</span>
          <span className="divider">·</span>
          <span>{Object.keys(stats.node_types).length} types</span>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// NODE DETAIL PANEL
// ============================================================================
function NodeDetail({ node, onClose, onExpand, onTrace }) {
  if (!node) return null;

  return (
    <div className="node-detail">
      <div className="node-detail-header">
        <span className="type-badge" style={{ background: NODE_COLORS[node.type] }}>
          {node.type}
        </span>
        <button className="close-btn" onClick={onClose}>✕</button>
      </div>
      <h3>{node.label}</h3>
      <div className="node-detail-body">
        {Object.entries(node)
          .filter(([k]) => !["id", "label", "type"].includes(k))
          .map(([k, v]) => (
            <div key={k} className="detail-row">
              <span className="detail-key">{k}</span>
              <span className="detail-value">{String(v ?? "—")}</span>
            </div>
          ))}
      </div>
      <div className="node-detail-actions">
        <button onClick={() => onExpand(node.id)}>Expand Neighbors</button>
        <button onClick={() => onTrace(node.id)}>Trace O2C Flow</button>
      </div>
    </div>
  );
}

// ============================================================================
// CHAT PANEL
// ============================================================================
function ChatPanel({ onHighlightNodes }) {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "I can answer questions about the SAP Order-to-Cash dataset. Try asking about sales orders, deliveries, billing documents, payments, or products.\n\nExample queries:\n• Which products have the most billing documents?\n• Trace the flow of billing document 90504204\n• Find sales orders that were delivered but not billed",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => `session_${Date.now()}`);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(scrollToBottom, [messages]);

  const sendQuery = async () => {
    const question = input.trim();
    if (!question || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);

    // Add a placeholder assistant message that we'll update as chunks arrive
    setMessages((prev) => [...prev, { role: "assistant", content: "", streaming: true }]);

    try {
      const res = await fetch(`${API_BASE}/api/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, session_id: sessionId }),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullContent = "";
      let sql = null;
      let blocked = false;
      let resultCount = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));

            if (event.type === "chunk") {
              fullContent += event.content;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: fullContent,
                };
                return updated;
              });
            } else if (event.type === "sql") {
              sql = event.sql;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  sql: event.sql,
                };
                return updated;
              });
            } else if (event.type === "nodes") {
              onHighlightNodes(event.highlighted_nodes);
            } else if (event.type === "blocked") {
              blocked = true;
              fullContent = event.answer;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: event.answer,
                  blocked: true,
                  streaming: false,
                };
                return updated;
              });
            } else if (event.type === "error") {
              fullContent = "An error occurred while processing your query. Please try rephrasing.";
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: fullContent,
                  sql: event.sql || null,
                  error: event.error,
                  streaming: false,
                };
                return updated;
              });
            } else if (event.type === "done") {
              resultCount = event.result_count;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  streaming: false,
                  resultCount: event.result_count,
                };
                return updated;
              });
            }
          } catch (e) {
            // Skip malformed SSE lines
          }
        }
      }
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: "Failed to reach the server. Is the backend running?",
          error: true,
          streaming: false,
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuery();
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <span>Query Assistant</span>
        <button
          className="clear-btn"
          onClick={async () => {
            await fetch(`${API_BASE}/api/clear-memory`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ session_id: sessionId }),
            });
            setMessages([messages[0]]);
          }}
        >
          Clear
        </button>
      </div>

      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            <div className={`message-content${msg.streaming ? ' streaming' : ''}`}>
              {msg.content}
              {msg.sql && !msg.streaming && (
                <details className="sql-details">
                  <summary>View SQL</summary>
                  <pre>{msg.sql}</pre>
                </details>
              )}
              {msg.resultCount != null && !msg.streaming && (
                <span className="result-count">{msg.resultCount} rows returned</span>
              )}
              {msg.blocked && <span className="blocked-badge">Off-topic query blocked</span>}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about orders, deliveries, billing..."
          rows={1}
          disabled={loading}
        />
        <button onClick={sendQuery} disabled={loading || !input.trim()} className="send-btn">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 2L11 13" />
            <path d="M22 2l-7 20-4-9-9-4 20-7z" />
          </svg>
        </button>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN APP
// ============================================================================
export default function App() {
  const [selectedNode, setSelectedNode] = useState(null);
  const [highlightNodes, setHighlightNodes] = useState([]);

  const handleExpand = async (nodeId) => {
    try {
      const res = await fetch(`${API_BASE}/api/graph/node/${nodeId}`);
      const data = await res.json();
      setHighlightNodes(data.nodes.map((n) => n.data.id));
    } catch (e) {
      console.error(e);
    }
  };

  const handleTrace = async (nodeId) => {
    try {
      const res = await fetch(`${API_BASE}/api/graph/trace/${nodeId}`);
      const data = await res.json();
      setHighlightNodes(data.nodes.map((n) => n.data.id));
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

        * { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
          --bg-primary: #0a0f1a;
          --bg-secondary: #111827;
          --bg-tertiary: #1e293b;
          --bg-hover: #263148;
          --border: #1e293b;
          --border-light: #334155;
          --text-primary: #f1f5f9;
          --text-secondary: #94a3b8;
          --text-muted: #64748b;
          --accent: #3b82f6;
          --accent-dim: #1e40af;
        }

        html, body, #root {
          height: 100%;
          overflow: hidden;
          background: var(--bg-primary);
          color: var(--text-primary);
          font-family: 'DM Sans', system-ui, sans-serif;
        }

        .app-layout {
          display: grid;
          grid-template-columns: 1fr 380px;
          grid-template-rows: 48px 1fr;
          height: 100vh;
          gap: 0;
        }

        .app-header {
          grid-column: 1 / -1;
          display: flex;
          align-items: center;
          padding: 0 16px;
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border);
          gap: 10px;
        }
        .app-header h1 { font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }
        .app-header .subtitle { font-size: 12px; color: var(--text-muted); font-weight: 400; }
        .logo-icon {
          width: 28px; height: 28px;
          background: linear-gradient(135deg, #3b82f6, #7c3aed);
          border-radius: 6px;
          display: flex; align-items: center; justify-content: center; flex-shrink: 0;
        }
        .logo-icon svg { color: white; }

        .graph-panel {
          position: relative;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          background: var(--bg-primary);
        }

        .graph-toolbar {
          display: flex; align-items: center; gap: 8px;
          padding: 8px 12px;
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border);
          flex-wrap: wrap;
        }

        .search-box {
          position: relative; display: flex; align-items: center; gap: 6px;
          background: var(--bg-tertiary);
          border: 1px solid var(--border-light);
          border-radius: 6px; padding: 5px 10px; flex: 0 0 200px;
        }
        .search-box svg { color: var(--text-muted); flex-shrink: 0; }
        .search-box input {
          background: none; border: none; color: var(--text-primary);
          font-size: 13px; font-family: inherit; outline: none; width: 100%;
        }
        .search-box input::placeholder { color: var(--text-muted); }

        .search-dropdown {
          position: absolute; top: 100%; left: 0; right: 0;
          background: var(--bg-secondary);
          border: 1px solid var(--border-light);
          border-radius: 0 0 6px 6px;
          max-height: 200px; overflow-y: auto; z-index: 100;
        }
        .search-result {
          display: flex; align-items: center; gap: 8px;
          padding: 6px 10px; cursor: pointer; font-size: 12px;
        }
        .search-result:hover { background: var(--bg-hover); }

        .type-badge {
          display: inline-block; padding: 1px 6px; border-radius: 3px;
          font-size: 10px; font-weight: 600; color: white;
          text-transform: uppercase; letter-spacing: 0.02em; white-space: nowrap;
        }

        .filter-pills { display: flex; gap: 4px; flex-wrap: wrap; }
        .pill {
          padding: 3px 10px; border-radius: 12px;
          border: 1px solid var(--border-light);
          background: transparent; color: var(--text-secondary);
          font-size: 11px; font-family: inherit; cursor: pointer; transition: all 0.15s;
        }
        .pill:hover { background: var(--bg-hover); color: var(--text-primary); }
        .pill.active {
          background: var(--pill-color, var(--accent));
          border-color: var(--pill-color, var(--accent)); color: white;
        }

        .reset-btn {
          margin-left: auto; padding: 3px 10px; border-radius: 6px;
          border: 1px solid var(--border-light); background: transparent;
          color: var(--text-secondary); font-size: 11px; font-family: inherit; cursor: pointer;
        }
        .reset-btn:hover { background: var(--bg-hover); color: var(--text-primary); }

        .graph-container { position: absolute; top: 42px; left: 0; right: 0; bottom: 24px; }

        .loading-overlay {
          position: absolute; inset: 0;
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          gap: 12px; color: var(--text-muted); font-size: 13px;
        }
        .spinner {
          width: 28px; height: 28px;
          border: 2px solid var(--border-light); border-top-color: var(--accent);
          border-radius: 50%; animation: spin 0.7s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        .stats-bar {
          display: flex; align-items: center; gap: 8px;
          padding: 4px 12px; background: var(--bg-secondary);
          border-top: 1px solid var(--border);
          font-size: 11px; color: var(--text-muted);
        }
        .stats-bar .divider { opacity: 0.3; }

        .node-detail {
          position: absolute; bottom: 40px; left: 12px; width: 320px;
          background: var(--bg-secondary);
          border: 1px solid var(--border-light); border-radius: 8px;
          padding: 12px; z-index: 50;
          box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }
        .node-detail-header {
          display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;
        }
        .node-detail h3 { font-size: 14px; font-weight: 600; margin-bottom: 10px; line-height: 1.3; }
        .close-btn {
          background: none; border: none; color: var(--text-muted);
          cursor: pointer; font-size: 14px; padding: 2px;
        }
        .node-detail-body { max-height: 200px; overflow-y: auto; margin-bottom: 10px; }
        .detail-row {
          display: flex; justify-content: space-between; padding: 3px 0;
          border-bottom: 1px solid var(--border); font-size: 11px; gap: 8px;
        }
        .detail-key {
          color: var(--text-muted); font-family: 'JetBrains Mono', monospace;
          font-size: 10px; flex-shrink: 0;
        }
        .detail-value { color: var(--text-secondary); text-align: right; word-break: break-all; }
        .node-detail-actions { display: flex; gap: 6px; }
        .node-detail-actions button {
          flex: 1; padding: 6px; border-radius: 5px;
          border: 1px solid var(--border-light); background: var(--bg-tertiary);
          color: var(--text-primary); font-size: 11px; font-family: inherit;
          cursor: pointer; transition: background 0.15s;
        }
        .node-detail-actions button:hover { background: var(--bg-hover); }

        .chat-panel {
          display: flex; flex-direction: column;
          background: var(--bg-secondary);
          border-left: 1px solid var(--border); overflow: hidden;
        }

        .chat-header {
          display: flex; align-items: center; gap: 8px;
          padding: 10px 14px; border-bottom: 1px solid var(--border);
          font-size: 13px; font-weight: 600; color: var(--text-primary);
        }
        .chat-header svg { color: var(--text-muted); }
        .clear-btn {
          margin-left: auto; padding: 2px 8px; border-radius: 4px;
          border: 1px solid var(--border-light); background: transparent;
          color: var(--text-muted); font-size: 11px; font-family: inherit; cursor: pointer;
        }
        .clear-btn:hover { background: var(--bg-hover); color: var(--text-primary); }

        .chat-messages {
          flex: 1; overflow-y: auto; padding: 12px;
          display: flex; flex-direction: column; gap: 10px;
        }

        .message { max-width: 95%; }
        .message.user { align-self: flex-end; }
        .message.assistant { align-self: flex-start; }

        .message-content {
          padding: 10px 14px; border-radius: 12px;
          font-size: 13px; line-height: 1.55;
          white-space: pre-wrap; word-break: break-word;
        }
        .message.user .message-content {
          background: var(--accent); color: white; border-bottom-right-radius: 4px;
        }
        .message.assistant .message-content {
          background: var(--bg-tertiary); color: var(--text-primary); border-bottom-left-radius: 4px;
        }

        .sql-details { margin-top: 8px; }
        .sql-details summary { font-size: 11px; color: var(--text-muted); cursor: pointer; user-select: none; }
        .sql-details pre {
          margin-top: 6px; padding: 8px; background: var(--bg-primary);
          border-radius: 6px; font-size: 11px;
          font-family: 'JetBrains Mono', monospace;
          color: var(--text-secondary); overflow-x: auto; white-space: pre-wrap;
        }

        .result-count { display: block; margin-top: 6px; font-size: 10px; color: var(--text-muted); }
        .blocked-badge {
          display: inline-block; margin-top: 6px; padding: 2px 6px;
          background: #dc2626; color: white; border-radius: 3px;
          font-size: 10px; font-weight: 600;
        }

        .message.assistant .message-content.streaming::after {
          content: '▌'; animation: blink 0.8s infinite; color: var(--accent); font-weight: bold;
        }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

        .chat-input-area {
          display: flex; align-items: flex-end; gap: 8px;
          padding: 10px 12px; border-top: 1px solid var(--border); background: var(--bg-secondary);
        }
        .chat-input-area textarea {
          flex: 1; background: var(--bg-tertiary);
          border: 1px solid var(--border-light); border-radius: 8px;
          padding: 8px 12px; color: var(--text-primary);
          font-size: 13px; font-family: inherit; resize: none; outline: none;
          max-height: 100px; line-height: 1.4;
        }
        .chat-input-area textarea::placeholder { color: var(--text-muted); }
        .chat-input-area textarea:focus { border-color: var(--accent); }

        .send-btn {
          width: 36px; height: 36px; border-radius: 8px; border: none;
          background: var(--accent); color: white; cursor: pointer;
          display: flex; align-items: center; justify-content: center;
          flex-shrink: 0; transition: background 0.15s;
        }
        .send-btn:hover { background: #2563eb; }
        .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border-light); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
      `}</style>

      <div className="app-layout">
        <header className="app-header">
          <div className="logo-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <circle cx="12" cy="12" r="3" />
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
            </svg>
          </div>
          <h1>O2C Graph Explorer</h1>
          <span className="subtitle">SAP Order-to-Cash · Graph Query System</span>
        </header>

        <div style={{ position: "relative", height: "calc(100vh - 90px)", overflow: "hidden" }}>
          <GraphView
            onNodeSelect={setSelectedNode}
            selectedNodes={[]}
            searchHighlight={highlightNodes}
          />
          <NodeDetail
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
            onExpand={handleExpand}
            onTrace={handleTrace}
          />
        </div>

        <ChatPanel onHighlightNodes={setHighlightNodes} />
      </div>
    </>
  );
}

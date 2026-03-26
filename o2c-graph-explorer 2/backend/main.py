"""
FastAPI Backend — SAP Order-to-Cash Graph Query System
=======================================================

Endpoints:
  GET  /api/health              — Health check
  GET  /api/graph               — Full graph data for Cytoscape.js
  GET  /api/graph/stats         — Graph statistics
  GET  /api/graph/node/{id}     — Node neighbors (expand node)
  GET  /api/graph/trace/{id}    — Trace full O2C flow from a node
  GET  /api/graph/search        — Search nodes by label
  POST /api/query               — Natural language query (LLM pipeline)
  POST /api/query/stream        — Streaming natural language query (SSE)
  POST /api/clear-memory        — Clear conversation memory

Run:
  uvicorn main:app --reload --port 8000
"""

import os
import json
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import build_database, export_graph_data
from graph import O2CGraph
from pipeline import query_pipeline, query_pipeline_stream, ConversationMemory


# ==============================================================================
# CONFIG
# ==============================================================================

DATA_DIR = os.environ.get("DATA_DIR", "./sap-o2c-data")
DB_PATH = os.environ.get("DB_PATH", "./data/o2c.db")


# ==============================================================================
# APP STATE (initialized on startup)
# ==============================================================================

class AppState:
    graph: O2CGraph = None
    memories: dict[str, ConversationMemory] = {}


state = AppState()


# ==============================================================================
# STARTUP / SHUTDOWN
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build database and graph on startup."""
    # Build SQLite database if it doesn't exist
    if not os.path.exists(DB_PATH):
        print(f"Building database from {DATA_DIR}...")
        build_database(DATA_DIR, DB_PATH)
        print("Database built successfully.")
    else:
        print(f"Using existing database: {DB_PATH}")

    # Build in-memory graph
    print("Building in-memory graph...")
    state.graph = O2CGraph(DB_PATH)
    stats = state.graph.get_stats()
    print(f"Graph loaded: {stats['total_nodes']} nodes, {stats['total_edges']} edges")

    yield  # App runs

    # Cleanup (nothing needed for SQLite + in-memory graph)
    print("Shutting down.")


# ==============================================================================
# APP INITIALIZATION
# ==============================================================================

app = FastAPI(
    title="SAP O2C Graph Query System",
    description="Graph-based data exploration and natural language querying for SAP Order-to-Cash data",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "*",  # For deployment — tighten in production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# REQUEST / RESPONSE MODELS
# ==============================================================================

class QueryRequest(BaseModel):
    question: str
    session_id: str = "default"


class QueryResponse(BaseModel):
    answer: str
    sql: str | None = None
    results: list[dict] | None = None
    highlighted_nodes: list[str] | None = None
    blocked: bool = False
    error: str | None = None
    highlighted_nodes: list[str] | None = None


class ClearMemoryRequest(BaseModel):
    session_id: str = "default"


# ==============================================================================
# HEALTH CHECK
# ==============================================================================

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "database": os.path.exists(DB_PATH),
        "graph_loaded": state.graph is not None,
    }


# ==============================================================================
# GRAPH ENDPOINTS
# ==============================================================================

@app.get("/api/graph")
async def get_graph(node_type: str = None):
    """
    Get full graph data for Cytoscape.js visualization.
    Optional: filter by node_type (Customer, SalesOrder, Delivery, etc.)
    """
    if not state.graph:
        raise HTTPException(status_code=503, detail="Graph not loaded")

    return state.graph.get_cytoscape_data(node_type=node_type)


@app.get("/api/graph/stats")
async def get_graph_stats():
    """Get graph statistics: node counts, edge counts by type."""
    if not state.graph:
        raise HTTPException(status_code=503, detail="Graph not loaded")

    return state.graph.get_stats()


@app.get("/api/graph/node/{node_id}")
async def get_node_neighbors(node_id: str):
    """
    Get a node and its direct neighbors (1-hop expansion).
    Used when user clicks a node in the graph UI.
    """
    if not state.graph:
        raise HTTPException(status_code=503, detail="Graph not loaded")

    result = state.graph.get_node_neighbors(node_id)
    if not result["nodes"]:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    return result


@app.get("/api/graph/trace/{node_id}")
async def trace_flow(node_id: str, direction: str = "both"):
    """
    Trace the full O2C flow from a given node.
    direction: 'upstream', 'downstream', or 'both'
    Used for "trace the flow of document X" queries.
    """
    if not state.graph:
        raise HTTPException(status_code=503, detail="Graph not loaded")

    if direction not in ("upstream", "downstream", "both"):
        raise HTTPException(status_code=400, detail="direction must be: upstream, downstream, both")

    result = state.graph.trace_flow(node_id, direction=direction)
    if not result["nodes"]:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    return result


@app.get("/api/graph/search")
async def search_nodes(q: str, node_type: str = None):
    """
    Search nodes by label (partial match).
    Used for the search bar in the frontend.
    """
    if not state.graph:
        raise HTTPException(status_code=503, detail="Graph not loaded")

    if len(q) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")

    results = state.graph.find_by_label(q, node_type=node_type)
    return {"results": results}


# ==============================================================================
# QUERY ENDPOINT (LLM Pipeline)
# ==============================================================================

@app.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """
    Natural language query against the O2C dataset.
    Uses the 3-stage LLM pipeline: Guardrail → NL→SQL → Summarize.
    Supports conversation memory via session_id.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Get or create conversation memory for this session
    if request.session_id not in state.memories:
        state.memories[request.session_id] = ConversationMemory(max_turns=5)
    memory = state.memories[request.session_id]

    # Run the pipeline
    result = query_pipeline(
        user_query=request.question.strip(),
        db_path=DB_PATH,
        memory=memory,
    )

    return QueryResponse(**result)


@app.post("/api/query/stream")
async def query_stream(request: QueryRequest):
    """
    Streaming natural language query via Server-Sent Events.
    The answer streams word-by-word for real-time UI feedback.
    SQL and highlighted nodes are sent as separate events before the answer stream.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if request.session_id not in state.memories:
        state.memories[request.session_id] = ConversationMemory(max_turns=5)
    memory = state.memories[request.session_id]

    return StreamingResponse(
        query_pipeline_stream(
            user_query=request.question.strip(),
            db_path=DB_PATH,
            memory=memory,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/clear-memory")
async def clear_memory(request: ClearMemoryRequest):
    """Clear conversation memory for a session."""
    if request.session_id in state.memories:
        state.memories[request.session_id].clear()
    return {"status": "cleared", "session_id": request.session_id}


# ==============================================================================
# SCHEMA ENDPOINT (for debugging / frontend display)
# ==============================================================================

@app.get("/api/schema")
async def get_schema():
    """Return database schema info for debugging."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=503, detail="Database not built")

    conn = sqlite3.connect(DB_PATH)
    tables = {}
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        for (table_name,) in cursor.fetchall():
            cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            tables[table_name] = {
                "columns": [{"name": c[1], "type": c[2]} for c in cols],
                "row_count": count,
            }
    finally:
        conn.close()

    return {"tables": tables}


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

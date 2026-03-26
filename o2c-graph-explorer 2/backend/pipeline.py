"""
LLM Query Pipeline Implementation
===================================
4-stage pipeline: Pre-filter → Guardrail → NL→SQL → Summarize (streaming)
With conversation memory + node highlighting.

Requires: google-generativeai, sqlite3
"""

import json
import re
import sqlite3
import google.generativeai as genai
from prompts import (
    GUARDRAIL_SYSTEM_PROMPT,
    NL_TO_SQL_SYSTEM_PROMPT,
    SUMMARIZE_SYSTEM_PROMPT,
    MEMORY_CONTEXT_TEMPLATE,
    BLOCKED_QUERY_RESPONSE,
    SQL_ERROR_RESPONSE,
    EMPTY_RESULT_RESPONSE,
)


# ==============================================================================
# CONFIG
# ==============================================================================

MODEL_NAME = "gemini-2.0-flash"  # Free tier, fast, good at SQL generation


# ==============================================================================
# CONVERSATION MEMORY
# ==============================================================================

class ConversationMemory:
    """Stores last N query exchanges for follow-up context."""

    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self.history: list[dict] = []

    def add(self, question: str, sql: str, answer: str):
        self.history.append({
            "question": question,
            "sql": sql,
            "answer": answer[:300],
        })
        if len(self.history) > self.max_turns:
            self.history.pop(0)

    def format_for_prompt(self) -> str:
        if not self.history:
            return ""
        lines = []
        for i, h in enumerate(self.history, 1):
            lines.append(f"Turn {i}:")
            lines.append(f"  Q: {h['question']}")
            lines.append(f"  SQL: {h['sql']}")
            lines.append(f"  A: {h['answer']}")
            lines.append("")
        return MEMORY_CONTEXT_TEMPLATE.format(history="\n".join(lines))

    def clear(self):
        self.history = []


# ==============================================================================
# LLM CALLS
# ==============================================================================

def call_gemini(system_prompt: str, user_message: str) -> str:
    """Single Gemini API call with system prompt."""
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=system_prompt,
    )
    response = model.generate_content(user_message)
    return response.text.strip()


def stream_gemini(system_prompt: str, user_message: str):
    """
    Streaming Gemini API call. Yields text chunks as they arrive.
    Used for Stage 3 (summarization) to give real-time feedback.
    """
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=system_prompt,
    )
    response = model.generate_content(user_message, stream=True)
    for chunk in response:
        if chunk.text:
            yield chunk.text


# ==============================================================================
# STAGE 0: PRE-FILTER (regex-based, no LLM cost)
# ==============================================================================
# Fast rejection of obviously off-topic queries before burning an LLM call.

# Patterns that are NEVER dataset-relevant
BLOCKED_PATTERNS = [
    # Creative writing / entertainment
    r"\b(write|compose|draft|create)\s+(a\s+)?(poem|story|essay|song|joke|haiku|limerick|script|letter|email)\b",
    r"\b(tell\s+me\s+a\s+joke|make\s+me\s+laugh|sing|rap)\b",
    # General knowledge
    r"\b(capital\s+of|president\s+of|who\s+(is|was)\s+(the\s+)?(king|queen|president|prime\s+minister))\b",
    r"\b(what\s+is\s+the\s+meaning\s+of\s+life)\b",
    r"\b(translate|definition\s+of|define)\b",
    # Coding / homework
    r"\b(write\s+(me\s+)?code|python\s+script|javascript|html|css|algorithm|leetcode|hackerrank)\b",
    r"\b(solve\s+this\s+equation|integrate|derivative|calculus|algebra)\b",
    # Personal / advice
    r"\b(relationship\s+advice|how\s+to\s+lose\s+weight|recipe\s+for|recommend\s+a\s+movie)\b",
    r"\b(what\s+should\s+i\s+(wear|eat|do\s+with\s+my\s+life))\b",
    # Jailbreak attempts
    r"\b(ignore\s+(previous|all|your)\s+(instructions|rules|prompts))\b",
    r"\b(you\s+are\s+now|act\s+as|pretend\s+(to\s+be|you\s+are)|roleplay)\b",
    r"\b(DAN|jailbreak|bypass|override|forget\s+your\s+(rules|instructions))\b",
    # News / external
    r"\b(stock\s+price|cryptocurrency|bitcoin|weather\s+in|news\s+about|latest\s+news)\b",
]

# Patterns that indicate dataset-relevant queries
ALLOWED_PATTERNS = [
    r"\b(sales?\s*order|SO\s*\d|purchase\s*order|PO\s*\d)\b",
    r"\b(delivery|deliveries|shipped|shipping|outbound)\b",
    r"\b(billing|invoice|billed|bill\s*doc)\b",
    r"\b(journal\s*entry|accounting\s*doc|posted|posting)\b",
    r"\b(payment|paid|cleared|clearing|receivable)\b",
    r"\b(customer|business\s*partner|sold\s*to)\b",
    r"\b(product|material|item)\b",
    r"\b(plant|warehouse|storage\s*location|shipping\s*point)\b",
    r"\b(order|revenue|amount|quantity|flow|trace|track)\b",
    r"\b(cancelled|incomplete|broken|missing|status)\b",
    r"\b(total|count|average|sum|highest|lowest|most|least|top|bottom)\b",
    r"\b(INR|rupee|currency)\b",
    r"\b\d{6,10}\b",  # Document numbers like 90504204, 740506
]


def pre_filter(query: str) -> str:
    """
    Fast regex pre-filter. Returns 'BLOCKED', 'ALLOWED', or 'UNCERTAIN'.
    """
    query_lower = query.lower().strip()

    if len(query_lower) < 3:
        return "BLOCKED"

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return "BLOCKED"

    matches = sum(1 for p in ALLOWED_PATTERNS if re.search(p, query_lower, re.IGNORECASE))
    if matches >= 2:
        return "ALLOWED"

    return "UNCERTAIN"


# ==============================================================================
# STAGE 1: GUARDRAIL (LLM-based, only for uncertain queries)
# ==============================================================================

def check_guardrail(user_query: str) -> bool:
    """
    Two-layer guardrail:
      Layer 1: Regex pre-filter (free, instant)
      Layer 2: LLM classifier (only if pre-filter is uncertain)
    Returns True if ALLOWED, False if BLOCKED.
    """
    pre_result = pre_filter(user_query)
    if pre_result == "BLOCKED":
        return False
    if pre_result == "ALLOWED":
        return True

    try:
        result = call_gemini(GUARDRAIL_SYSTEM_PROMPT, user_query)
        return "BLOCKED" not in result.upper()
    except Exception:
        return True


# ==============================================================================
# STAGE 2: NL → SQL
# ==============================================================================

def generate_sql(user_query: str, memory: ConversationMemory) -> str:
    """Convert natural language question to SQLite SQL."""
    system = NL_TO_SQL_SYSTEM_PROMPT
    memory_context = memory.format_for_prompt()
    if memory_context:
        system += "\n" + memory_context

    raw_sql = call_gemini(system, user_query)

    sql = raw_sql.strip()
    if sql.startswith("```"):
        sql = sql.split("\n", 1)[1] if "\n" in sql else sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    sql = sql.strip()
    if sql.lower().startswith("sql\n"):
        sql = sql[4:]
    elif sql.lower().startswith("sql "):
        sql = sql[4:]

    return sql.strip()


# ==============================================================================
# SQL EXECUTION
# ==============================================================================

def execute_sql(db_path: str, sql: str) -> tuple[list[dict], list[str] | None]:
    """
    Execute SQL against SQLite database.
    SECURITY: Read-only connection + multi-layer validation.
    """
    sql_upper = sql.strip().upper()

    if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
        raise ValueError("Only SELECT queries are allowed.")

    dangerous_keywords = [
        "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE",
        "EXEC", "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX",
        "REPLACE", "GRANT", "REVOKE",
    ]
    for kw in dangerous_keywords:
        if re.search(rf"\b{kw}\b", sql_upper):
            raise ValueError(f"Disallowed SQL keyword: {kw}")

    statements = [s.strip() for s in sql.split(";") if s.strip()]
    if len(statements) > 1:
        raise ValueError("Multiple SQL statements are not allowed.")

    if "INTO" in sql_upper and "OUTFILE" in sql_upper:
        raise ValueError("File operations are not allowed.")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        results = [dict(row) for row in rows]
        return results, columns
    finally:
        conn.close()


# ==============================================================================
# STAGE 3: SUMMARIZE RESULTS
# ==============================================================================

def summarize_results(user_query: str, sql: str, results: list[dict]) -> str:
    """Non-streaming summarization."""
    if not results:
        return EMPTY_RESULT_RESPONSE

    display_results = results[:30]
    truncated = len(results) > 30

    user_message = f"""Question: {user_query}

SQL Executed:
{sql}

Results ({len(results)} rows{', showing first 30' if truncated else ''}):
{json.dumps(display_results, indent=2, default=str)}"""

    return call_gemini(SUMMARIZE_SYSTEM_PROMPT, user_message)


def summarize_results_stream(user_query: str, sql: str, results: list[dict]):
    """Streaming summarization. Yields text chunks."""
    if not results:
        yield EMPTY_RESULT_RESPONSE
        return

    display_results = results[:30]
    truncated = len(results) > 30

    user_message = f"""Question: {user_query}

SQL Executed:
{sql}

Results ({len(results)} rows{', showing first 30' if truncated else ''}):
{json.dumps(display_results, indent=2, default=str)}"""

    yield from stream_gemini(SUMMARIZE_SYSTEM_PROMPT, user_message)


# ==============================================================================
# NODE ID EXTRACTION (for graph highlighting)
# ==============================================================================

COLUMN_TO_PREFIX = {
    "salesOrder": "SO_", "salesorder": "SO_", "sales_order": "SO_",
    "deliveryDocument": "DEL_", "deliverydocument": "DEL_", "delivery_document": "DEL_", "deliveryDoc": "DEL_",
    "billingDocument": "BILL_", "billingdocument": "BILL_", "billing_document": "BILL_",
    "accountingDocument": "JE_", "accountingdocument": "JE_", "accounting_document": "JE_",
    "payDoc": "PAY_",
    "businessPartner": "CUST_", "soldToParty": "CUST_", "soldtoparty": "CUST_", "sold_to_party": "CUST_", "customer": "CUST_",
    "material": "PROD_", "product": "PROD_",
    "plant": "PLANT_", "productionPlant": "PLANT_",
}


def extract_node_ids(results: list[dict]) -> list[str]:
    """Scan SQL results for entity ID columns → graph node IDs."""
    node_ids = set()
    for row in results[:50]:
        for col, value in row.items():
            col_lower = col.lower() if col else ""
            prefix = COLUMN_TO_PREFIX.get(col) or COLUMN_TO_PREFIX.get(col_lower)
            if prefix and value is not None and str(value).strip():
                node_ids.add(f"{prefix}{value}")
    return list(node_ids)


# ==============================================================================
# FULL PIPELINE (non-streaming)
# ==============================================================================

def query_pipeline(user_query: str, db_path: str, memory: ConversationMemory) -> dict:
    """Full pipeline returning complete result dict."""
    if not check_guardrail(user_query):
        return {"answer": BLOCKED_QUERY_RESPONSE, "sql": None, "results": None,
                "highlighted_nodes": None, "blocked": True, "error": None}

    try:
        sql = generate_sql(user_query, memory)
    except Exception as e:
        return {"answer": SQL_ERROR_RESPONSE, "sql": None, "results": None,
                "highlighted_nodes": None, "blocked": False, "error": f"SQL generation failed: {str(e)}"}

    try:
        results, columns = execute_sql(db_path, sql)
    except Exception as e:
        return {"answer": SQL_ERROR_RESPONSE, "sql": sql, "results": None,
                "highlighted_nodes": None, "blocked": False, "error": f"SQL execution failed: {str(e)}"}

    try:
        answer = summarize_results(user_query, sql, results)
    except Exception:
        answer = f"Found {len(results)} results but couldn't generate a summary."

    highlighted_nodes = extract_node_ids(results)
    memory.add(user_query, sql, answer)

    return {"answer": answer, "sql": sql, "highlighted_nodes": highlighted_nodes,
            "results": results[:50], "blocked": False, "error": None}


# ==============================================================================
# STREAMING PIPELINE
# ==============================================================================

def query_pipeline_stream(user_query: str, db_path: str, memory: ConversationMemory):
    """
    Streaming pipeline. Stages 0-2 run instantly.
    Stage 3 streams via Server-Sent Events.

    Yields SSE-formatted strings:
      data: {"type": "sql", "sql": "..."}
      data: {"type": "chunk", "content": "..."}
      data: {"type": "nodes", "highlighted_nodes": [...]}
      data: {"type": "done", "result_count": N}
      data: {"type": "blocked", "answer": "..."}
      data: {"type": "error", "error": "..."}
    """
    if not check_guardrail(user_query):
        yield f"data: {json.dumps({'type': 'blocked', 'answer': BLOCKED_QUERY_RESPONSE})}\n\n"
        return

    try:
        sql = generate_sql(user_query, memory)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'error': f'SQL generation failed: {str(e)}'})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'sql', 'sql': sql})}\n\n"

    try:
        results, columns = execute_sql(db_path, sql)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'error': f'SQL execution failed: {str(e)}', 'sql': sql})}\n\n"
        return

    highlighted_nodes = extract_node_ids(results)
    if highlighted_nodes:
        yield f"data: {json.dumps({'type': 'nodes', 'highlighted_nodes': highlighted_nodes})}\n\n"

    if not results:
        yield f"data: {json.dumps({'type': 'chunk', 'content': EMPTY_RESULT_RESPONSE})}\n\n"
        full_answer = EMPTY_RESULT_RESPONSE
    else:
        full_answer = ""
        try:
            for chunk in summarize_results_stream(user_query, sql, results):
                full_answer += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except Exception:
            fallback = f"Found {len(results)} results but couldn't generate a summary."
            yield f"data: {json.dumps({'type': 'chunk', 'content': fallback})}\n\n"
            full_answer = fallback

    memory.add(user_query, sql, full_answer)
    yield f"data: {json.dumps({'type': 'done', 'result_count': len(results)})}\n\n"

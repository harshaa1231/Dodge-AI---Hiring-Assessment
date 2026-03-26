# Claude.ai Chat Session — O2C Graph Explorer
## AI-Assisted Architecture & Development Transcript

**Tool:** Claude.ai (Opus)  
**Date:** March 23-24, 2026  
**Purpose:** Architecture planning, data exploration, schema design, code generation, testing

---

## Prompt 1: Initial Architecture Planning

**User:**
> [Uploaded assignment spec] Plan on using Claude Code. Also want to add 1-2 of these optional extensions: Natural language to SQL, Highlighting nodes, Semantic search, Streaming responses, Conversation memory, Graph clustering.

**Claude's Response Summary:**
- Recommended tech stack: FastAPI + SQLite + NetworkX (backend), React + Cytoscape.js (frontend), Google Gemini free tier (LLM)
- Chose SQLite over Neo4j — justified by dataset size (1,634 records). Neo4j would add deployment complexity for zero performance benefit at this scale.
- Recommended NL→SQL + Conversation Memory as the two extensions (highest impact-to-effort ratio)
- Created 3-day execution plan with priorities

**Why this matters:** Established key architectural decisions before writing any code. The SQLite-over-Neo4j decision was a tradeoff analysis, not a default choice.

---

## Prompt 2: Dataset Exploration & Schema Design

**User:**
> [Uploaded sap-order-to-cash-dataset.zip] I have it but need help reading it.

**Claude's Analysis:**
- Extracted and inspected all 19 JSONL entity directories
- Identified exact column names, data types, and record counts for every entity
- **Verified all foreign key relationships programmatically:**
  - billing_items.referenceSdDocument → delivery_headers: 83/83 match (100%)
  - delivery_items.referenceSdDocument → sales_order_headers: 86/86 match (100%)
  - billing_headers.accountingDocument → journal_entries: 123/163 match (75% — data gap, not a bug)
  - payments.clearingAccountingDocument → journal_entries: 56 overlap
  - sales_order_headers.soldToParty → business_partners: 8/8 match (100%)
- Designed complete graph schema: 8 node types, 7 edge types, all with verified join logic
- Identified nested fields requiring flattening (time dicts in 4 tables)

**Key Finding:** 60 edges would be "broken" due to billing documents referencing journal entry IDs not present in the dataset. This was confirmed as a data gap, not a code bug — the graph module filters these automatically.

**Why this matters:** Data exploration BEFORE code generation prevented schema errors that would have cascaded into broken queries.

---

## Prompt 3: LLM Prompting Strategy

**User:**
> What should I build for you first? → LLM prompting strategy + guardrails

**Claude's Design:**
- **3-stage pipeline architecture:**
  - Stage 1: Guardrail classifier (cheap, one-word response, rejects off-topic before expensive SQL generation)
  - Stage 2: NL→SQL with full schema context (~2,500 tokens of table/column/FK documentation in the system prompt)
  - Stage 3: Result summarization (sees question + SQL + raw results, generates natural language answer)
- **Conversation memory design:** Last 5 turns appended to NL→SQL prompt, answers truncated to 300 chars for token efficiency
- **SQL security:** Two-layer validation — guardrail blocks off-topic queries, execute_sql() validates statement type + blocks dangerous keywords + read-only connection

**Key Decision:** Decomposing into 3 stages instead of one monolithic prompt. A single prompt that does classification + SQL + summarization is unreliable. Each stage has a focused system prompt optimized for one task.

---

## Prompt 4: Data Ingestion Testing

**User:**
> What should I build next? → Data ingestion + SQLite setup

**Claude Built & Tested:**
- Complete ingestion script: 17 tables, explicit schemas with correct types, 22 FK indexes
- Flattening logic for nested time dicts ({hours, minutes, seconds} → "HH:MM:SS")
- Graph data export function returning Cytoscape.js-compatible format
- **Ran against real data:** 1,634 rows loaded, 432KB database, 713 nodes, 825 edges

**Verification Queries (all 3 assignment examples tested against real data):**
```
Q1: Products with most billing docs → FACESERUM & SUNSCREEN tied at 22
Q2: Trace billing doc 90504204 → Customer 320000083 → SO 740509 → DEL 80738040 → BILL 90504204 → JE 9400000205 → UNPAID
Q3: Broken flows → 3 delivered-not-billed, 14 no-delivery, 24 missing journal entries
```

**Why this matters:** Testing example queries against real data before building the LLM integration ensured the schema and join logic were correct.

---

## Prompt 5: Query Testing & Data Insights

**User:**
> Help me test the example queries

**Claude ran comprehensive SQL tests:**
- All 3 assignment example queries verified with exact numbers
- Additional queries: revenue by customer (Nelson Fitzpatrick #1 at INR 27,777), cancelled billing docs (80 docs / INR 30,079), orders by month, plant utilization (Cookmouth handles 84% of deliveries)
- These exact numbers serve as validation benchmarks — if the LLM generates SQL that returns different numbers, the prompt needs fixing

---

## Prompt 6: Guardrail Hardening + Streaming

**User:**
> Do the Streaming responses from the LLM and also check if the guardrails are strong enough

**Claude's Improvements:**
- **Added regex pre-filter (Layer 0):** 15+ blocked patterns (creative writing, general knowledge, jailbreak attempts like "ignore your instructions", "you are now DAN", "pretend to be") + 13 allowed patterns (dataset-specific terms). Catches ~40% of queries without any LLM call.
- **Hardened LLM guardrail prompt:** Added "if unsure, respond BLOCKED", anti-jailbreak instruction, explicit edge cases
- **Hardened SQL execution:** Added PRAGMA, VACUUM, REINDEX, REPLACE to blocklist. Added multi-statement detection. Added INTO/OUTFILE check.
- **Added streaming pipeline:** `query_pipeline_stream()` yields SSE events — SQL first, then highlighted nodes, then answer chunks word-by-word
- **Tested pre-filter:** 21/24 test cases passed. The 3 "failures" were safe (UNCERTAIN queries that the LLM layer catches correctly)

---

## Prompt 7: Node Highlighting (Bonus Extension)

**User:**
> What optional features have we added out of the 5 they gave?

**Claude identified gap:** Node highlighting was stubbed but not wired.

**Fix:**
- Added `extract_node_ids()` function that scans SQL result columns for entity IDs (salesOrder, billingDocument, customer, etc.) and maps them to graph node IDs (SO_740509, BILL_90504204, etc.)
- Updated API response to include `highlighted_nodes` array
- Wired frontend to receive highlighted_nodes and apply CSS classes to matching Cytoscape.js nodes

---

## Architecture Decisions Summary

| Decision | Chosen | Rejected | Reasoning |
|----------|--------|----------|-----------|
| Database | SQLite | Neo4j, PostgreSQL | 1,634 rows — graph DB adds complexity with zero benefit. SQLite enables direct NL→SQL |
| Graph engine | NetworkX (in-memory) | Neo4j, JanusGraph | Small dataset, loaded once at startup. No infrastructure needed |
| LLM | Gemini 2.0 Flash | GPT-4, Claude API | Free tier with generous limits. Fast enough for SQL generation |
| Query pipeline | 3-stage decomposition | Single monolithic prompt | Each stage optimized for one task. More reliable SQL generation |
| Guardrails | Regex pre-filter + LLM | LLM only | Pre-filter is instant and free. Catches jailbreaks without API cost |
| Frontend | Single-file React | Component library | Evaluators can read one file. No unnecessary abstraction |
| DB build timing | Docker build time | Runtime | Eliminates cold start latency on Render free tier |

---

## Final Extension Coverage

| Extension | Implemented | Depth |
|-----------|-------------|-------|
| NL → SQL translation | ✅ | Full schema context, SQL cleaning, error handling |
| Conversation memory | ✅ | 5-turn history, token-efficient, session-based |
| Node highlighting | ✅ | Column-to-prefix mapping, automatic extraction |
| Streaming responses | ✅ | SSE protocol, chunked summarization, blinking cursor |
| Semantic search | ❌ | Not implemented |
| Graph clustering | ❌ | Not implemented |

# Conversational Signal Creation — Design

**Date:** 2026-03-01
**Status:** Approved

---

## Problem

Signal creation is currently one-shot: user types a prompt, LLM parses it, signal is stored. Ambiguous prompts fail silently or produce poor signals. There's no way to define dashboard visualization type or distinguish between dashboard metrics and alert conditions.

---

## Solution

Replace the single-prompt modal with a terminal-style conversational agent that gathers requirements iteratively before storing anything. The agent is adaptive — it skips questions when the prompt is already precise, asks when ambiguity exists.

---

## Data Model

New fields added to `Signal`:

```python
description: str                          # high-level purpose, synthesized by agent
metric_description: str                   # technical metric spec, agent-generated
conversation_history: list[dict]          # [{role, content}] full transcript
dashboard_chart_type: str                 # "line" | "bar" | "gauge" — agent picks
```

- `description` — human-readable purpose: *"Monitor Bitcoin price and alert when it drops below my threshold"*
- `metric_description` — technical spec: *"BTC/USD spot price in USD, compared against 45000 using `<` operator, sourced via web search"*
- `conversation_history` — stored but hidden by default; accessible via "Creation History" collapsed section on signal detail page
- `dashboard_chart_type` — one chart type per signal (simple mode); agent selects based on topic (price → line, boolean → gauge, count → bar)

---

## Conversation Flow

The modal operates in two phases:

### Phase 1: Chat

Terminal-style Q&A. Agent evaluates the initial prompt and asks one question at a time, with lettered options where applicable:

```
[AGENT] > Analyzing your prompt...

[AGENT] > What condition should trigger an alert?
         [A] Price goes above a threshold
         [B] Price drops below a threshold
         [C] Just track it on the dashboard, no alert

[USER]  > B

[AGENT] > What's your threshold? (e.g. 50000)

[USER]  > 45000

[AGENT] > How often should I check?
         [A] Every 15 min   [B] Every hour (default)   [C] Every 6 hours

[USER]  > B

[AGENT] > Requirements clear. Generating spec...
```

When the prompt is already precise, the agent skips straight to the confirmation phase.

### Phase 2: Confirmation Card

Chat fades, replaced by a structured summary card. User sees the consolidated spec — not the raw transcript:

```
┌─ SIGNAL SPEC ──────────────────────────────┐
│ NAME       Bitcoin Price Monitor           │
│ METRIC     BTC/USD spot price (USD)        │
│ ALERT      triggers when price < 45,000    │
│ DASHBOARD  Line chart — price over time    │
│ INTERVAL   Every 60 min                    │
└────────────────────────────────────────────┘
[ CONFIRM & CREATE ]   [ ← REVISE ]
```

- **CONFIRM** — POSTs to `/signals` with full history + synthesized fields; signal is stored
- **REVISE** — returns to chat phase with history intact

Nothing is stored until CONFIRM is clicked.

---

## Backend Architecture

### New endpoint

```
POST /signals/chat
  body:    { history: [{role, content}], message: str }
  returns: { message: str, done: bool, spec?: SignalSpec }
```

`done: true` signals the agent is satisfied. `spec` contains the full synthesized output:

```python
class SignalSpec(BaseModel):
    name: str
    description: str
    metric_description: str
    dashboard_chart_type: str       # "line" | "bar" | "gauge"
    topic: str
    condition: str                  # ">", "<", ">=", "<=", "==", "contains"
    threshold: Optional[float]
    unit: Optional[str]
    search_query: str
    interval_minutes: int
```

### Extended create endpoint

```
POST /signals  (existing, extended)
  body adds: history, description, metric_description, dashboard_chart_type
```

### New LLM function

`run_chat_turn(history, message) -> ChatTurnResult` in `llm.py`.

System prompt instructs the agent to:
1. Evaluate ambiguity of the initial prompt
2. Ask one question at a time with lettered options
3. Cover: alert condition + threshold, dashboard chart type (auto-selected), interval
4. When confident, return `done: true` with full `SignalSpec`

The existing `parse_prompt()` is **retired** — the chat flow replaces it entirely.

### Stateless backend

The server holds no conversation state. The browser holds `history: [{role, content}]` in a JS array and sends it with every request. This fits FastAPI's stateless nature perfectly.

---

## Frontend

### Modal phases

The existing `create_modal.html` partial is replaced with a two-phase modal:

1. **Chat phase** — scrollable terminal log + single-line input at bottom + blinking cursor
2. **Confirmation phase** — spec card + CONFIRM / REVISE buttons

Transition is animated (chat fades out, card fades in).

### Conversation history (hidden by default)

On the signal detail page, a collapsed "Creation History" section shows the full transcript. Not shown on dashboard cards or the modal confirmation.

---

## What's NOT changing

- All existing signal operations (delete, toggle-alert, run-now, update) are unchanged
- The dashboard card layout is unchanged (chart type field is new but additive)
- The `ParsedSignal` model fields are preserved inside `Signal.parsed`

---

## Success Criteria

- [ ] Vague prompts (e.g. "monitor Tesla") trigger clarifying questions
- [ ] Precise prompts (e.g. "alert me when gold > 2000 USD") skip straight to confirmation
- [ ] Nothing is stored until CONFIRM is clicked
- [ ] Signal detail page shows creation history in a collapsed section
- [ ] `description` and `metric_description` both appear on signal detail page

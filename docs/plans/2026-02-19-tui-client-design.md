# Second Brain TUI Client — Design Document

A split-pane terminal client for the Second Brain API, built with Bubble Tea (Go). Conversation and graph exploration side by side.

## Problem

The Second Brain API has no user-facing interface. The first client should support both quick one-shot commands and an interactive session where the user converses with their knowledge base while visually exploring the underlying graph.

## Stack

- **Language:** Go
- **TUI framework:** Bubble Tea (Charm ecosystem)
- **Components:** Bubbles (viewport, textinput, spinner)
- **Styling:** Lip Gloss
- **CLI parsing:** Cobra
- **Distribution:** Single static binary

## API Contract

The client talks to the FastAPI server over HTTP. Four endpoints:

| Endpoint | Purpose | Request | Response |
|---|---|---|---|
| `POST /ingest` | One-shot knowledge intake | `{text, hints?}` | `{summary}` |
| `POST /recall` | One-shot question answering | `{question, hints?}` | `{answer, context{nodes, edges}}` |
| `POST /converse` | Interactive conversation | `{message, history[]}` | `{response, context?{nodes, edges}}` |
| `GET /graph/{id}` | Graph traversal | — | `{node, connections[]}` |

### Hints

Both `/ingest` and `/recall` accept an optional `hints` field: a list of node IDs suggesting potentially related nodes. The agent exercises judgment on whether to use them. This supports clients that want to provide relationship guidance without going through the conversation agent.

### Context

The `context` in responses is the **curated subset** of nodes and edges the agent deemed relevant to its answer — not the full subgraph it explored. The recall agent's answer tool call specifies both the natural language answer and the specific node/edge IDs it's citing.

For `/converse`, context is present when the conversation agent performed a recall. When it only ingested, context is absent and the client leaves the previous graph state unchanged.

### History

Each item in the `/converse` history array includes the full exchange structure:

```json
{
  "user": "what do I know about GTD?",
  "assistant": {
    "response": "You have several notes...",
    "context": {"nodes": [...], "edges": [...]}
  }
}
```

The client maintains a rolling window (capped at N turns). Context does not stack across turns — each response replaces the previous context.

### Conversation Agent

The `/converse` endpoint is backed by a conversation agent that has ingest and recall as tools. It handles intent routing (is this a question or new knowledge?), follow-up context, and multi-turn coherence. The client sends plain messages and history; the agent decides what to do.

## Interaction Modes

### Command Mode

One-shot invocations that exit after completion:

- `brain ingest "some thought or idea"` — POST /ingest, prints summary
- `brain recall "what do I know about X?"` — POST /recall, prints answer and context summary
- `brain graph <id>` — GET /graph/{id}, prints node and connections

### REPL Mode

`brain` with no subcommand launches the interactive TUI.

- Free text goes to POST /converse with history
- `/graph` — toggle focus to graph panel
- `/clear` — drop history buffer and graph, start fresh conversation
- `/quit` or Ctrl+C — exit
- `@NodeName` — reference a node from the current graph panel (autocomplete from visible nodes)

No mode toggle needed — the conversation agent decides whether to ingest, recall, or both.

## TUI Layout

Split-pane: conversation on the left, graph on the right.

```
┌─────────────────────────────┬────────────────────────────┐
│ Conversation                │ Graph                      │
├─────────────────────────────┤                            │
│                             │  [entity] GTD              │
│ You: What do I know about   │    ──relates_to──>         │
│ GTD?                        │  [entity] Agile            │
│                             │    ──references──>         │
│ Brain: You have 3 notes     │  [note] Sprint retro...    │
│ connecting GTD to your      │    ──derived_from──>       │
│ productivity system...      │  [note] GTD workflow...    │
│                             │  > [entity] Productivity   │
│ You: How does @Agile fit    │                            │
│ in?                         │                            │
│                             │                            │
│ Brain: Your note from last  │                            │
│ week draws a parallel...    │                            │
│                             │                            │
├─────────────────────────────┤────────────────────────────┤
│ > @Productivity tell me _   │ ↑↓ nav  ENTER expand  TAB │
└─────────────────────────────┴────────────────────────────┘
```

### Conversation Panel

- Scrollable chat history
- Input bar at bottom with `@` autocomplete from graph panel nodes
- Spinner while waiting for /converse response

### Graph Panel

- Displays the curated nodes and edges from the last conversation response that included context
- Independently navigable with arrow keys
- **Enter** on a node expands its neighbors via `GET /graph/{id}` — pure graph traversal, no LLM call
- Graph expansion does not affect conversation context
- Only conversation responses with context update the graph panel; ingest-only responses leave it unchanged

### Interaction Flow

The two panels are synchronized but independently operable:

1. Conversation responses with context update the graph panel
2. User can browse the graph freely (expand nodes, follow edges) without triggering the conversation agent
3. User can reference graph nodes in conversation with `@` syntax — the client resolves the node ID and includes it in the /converse request
4. TAB switches focus between conversation input and graph navigation

## Client State

```
State {
    history:  []Exchange          // rolling window, last N turns
    context:  {nodes, edges}      // from last response with context
    graph:    {nodes, edges}      // currently displayed (may differ from context after manual expansion)
    input:    string              // current input buffer
    focus:    chat | graph        // which panel has focus
    loading:  bool                // waiting for server response
}
```

`context` is the curated set from the last conversation response. `graph` starts as a copy of `context` but diverges as the user manually expands nodes.

## Project Structure

```
client/
├── cmd/
│   └── brain/
│       └── main.go              # entry point, Cobra CLI parsing
├── internal/
│   ├── api/
│   │   └── client.go            # HTTP client for all endpoints
│   ├── tui/
│   │   ├── model.go             # Bubble Tea model (state)
│   │   ├── update.go            # message handling, key bindings
│   │   ├── view.go              # rendering (layout, panels)
│   │   ├── chat.go              # chat panel component
│   │   ├── graph.go             # graph panel component
│   │   └── input.go             # input bar with @ autocomplete
│   └── types/
│       └── types.go             # shared types (Node, Edge, Exchange)
├── go.mod
└── go.sum
```

Dependencies:
- `github.com/charmbracelet/bubbletea` — TUI framework
- `github.com/charmbracelet/bubbles` — reusable components
- `github.com/charmbracelet/lipgloss` — styling
- `github.com/spf13/cobra` — CLI command routing

Build: `go build -o brain ./cmd/brain`

## Error Handling

- **Server unreachable:** display "Cannot reach server at {url}" in the conversation panel. TUI stays open, graph panel remains interactive if populated.
- **Slow responses:** spinner in conversation pane while waiting. Graph panel stays interactive.
- **Unknown `@` reference:** if `@Something` isn't in the current graph, send as plain text. The conversation agent can still attempt to resolve it.
- **Server URL:** configurable via `--server` flag or `BRAIN_SERVER_URL` env var, defaulting to `http://localhost:8000`.

## Deferred

- Voice input integration
- Graph visualization with actual spatial layout (force-directed, etc.)
- Export/share conversation sessions
- Theming and color customization
- Multi-server support (connect to multiple brains)

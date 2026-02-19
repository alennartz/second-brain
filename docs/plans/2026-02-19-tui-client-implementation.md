# TUI Client Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Go TUI client for the Second Brain API with split-pane conversation + graph exploration.

**Architecture:** Standalone HTTP client built with Bubble Tea (Charm ecosystem). Cobra handles CLI parsing for command mode (one-shot `brain ingest/recall/graph`) and launches the TUI for REPL mode (`brain` with no subcommand). The TUI uses a split-pane layout with a conversation panel on the left and a graph panel on the right.

**Tech Stack:** Go, Bubble Tea, Bubbles, Lip Gloss, Cobra

**Design doc:** `docs/plans/2026-02-19-tui-client-design.md`

**Note on server API:** The current server has `POST /ingest` (`{text, source}` → `{summary}`) and `POST /recall` (`{question}` → `{answer}`). The design calls for changes (hints, context in responses, /converse endpoint). This plan builds the client against the designed API contract. Endpoints that don't exist yet can be tested with httptest mocks and integrated later when the server catches up.

---

### Task 1: Go Project Scaffolding

**Files:**
- Create: `client/go.mod`
- Create: `client/cmd/brain/main.go`
- Create: `client/internal/types/types.go`
- Create: `client/internal/api/client.go`
- Create: `client/internal/tui/model.go`

**Step 1: Initialize Go module and directory structure**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain
mkdir -p client/cmd/brain client/internal/types client/internal/api client/internal/tui
cd client
go mod init second-brain-client
```

**Step 2: Add dependencies**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go get github.com/charmbracelet/bubbletea@latest
go get github.com/charmbracelet/bubbles@latest
go get github.com/charmbracelet/lipgloss@latest
go get github.com/spf13/cobra@latest
```

**Step 3: Create minimal main.go that compiles**

`client/cmd/brain/main.go`:
```go
package main

import "fmt"

func main() {
	fmt.Println("brain")
}
```

**Step 4: Verify it builds**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go build -o brain ./cmd/brain
./brain
```

Expected: prints `brain`

**Step 5: Commit**

```bash
git add client/
git commit -m "feat(client): scaffold Go project with dependencies"
```

---

### Task 2: Shared Types

**Files:**
- Create: `client/internal/types/types.go`
- Create: `client/internal/types/types_test.go`

**Step 1: Write test for JSON round-trip of API types**

`client/internal/types/types_test.go`:
```go
package types_test

import (
	"encoding/json"
	"testing"

	"second-brain-client/internal/types"
)

func TestNodeJSON(t *testing.T) {
	n := types.Node{
		ID:          "note:abc123",
		Table:       "note",
		Content:     "GTD workflow overview",
		Name:        "",
		Description: "",
	}
	data, err := json.Marshal(n)
	if err != nil {
		t.Fatal(err)
	}
	var got types.Node
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatal(err)
	}
	if got.ID != n.ID {
		t.Errorf("got ID %q, want %q", got.ID, n.ID)
	}
}

func TestConverseRequestJSON(t *testing.T) {
	req := types.ConverseRequest{
		Message: "What do I know about GTD?",
		History: []types.Exchange{
			{
				User: "previous question",
				Assistant: types.AssistantResponse{
					Response: "previous answer",
					Context: &types.Context{
						Nodes: []types.Node{{ID: "note:1", Table: "note"}},
						Edges: []types.Edge{{ID: "relates_to:1", Table: "relates_to", From: "entity:1", To: "entity:2"}},
					},
				},
			},
		},
	}
	data, err := json.Marshal(req)
	if err != nil {
		t.Fatal(err)
	}
	var got types.ConverseRequest
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatal(err)
	}
	if len(got.History) != 1 {
		t.Fatalf("got %d history items, want 1", len(got.History))
	}
	if got.History[0].Assistant.Context == nil {
		t.Fatal("expected context, got nil")
	}
	if len(got.History[0].Assistant.Context.Nodes) != 1 {
		t.Fatalf("got %d nodes, want 1", len(got.History[0].Assistant.Context.Nodes))
	}
}

func TestConverseResponseNilContext(t *testing.T) {
	raw := `{"response":"Ingested your thought.","context":null}`
	var resp types.ConverseResponse
	if err := json.Unmarshal([]byte(raw), &resp); err != nil {
		t.Fatal(err)
	}
	if resp.Response != "Ingested your thought." {
		t.Errorf("got response %q", resp.Response)
	}
	if resp.Context != nil {
		t.Error("expected nil context for ingest-only response")
	}
}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/types/ -v
```

Expected: FAIL — package doesn't exist yet.

**Step 3: Implement types**

`client/internal/types/types.go`:
```go
package types

// Node represents a note or entity in the knowledge graph.
type Node struct {
	ID          string `json:"id"`
	Table       string `json:"table"`
	Content     string `json:"content,omitempty"`
	Name        string `json:"name,omitempty"`
	Type        string `json:"type,omitempty"`
	Description string `json:"description,omitempty"`
	Summary     string `json:"summary,omitempty"`
}

// Edge represents a relationship between two nodes.
type Edge struct {
	ID      string `json:"id"`
	Table   string `json:"table"`
	From    string `json:"from"`
	To      string `json:"to"`
	Context string `json:"context,omitempty"`
}

// Context is the curated subset of nodes/edges the agent deemed relevant.
type Context struct {
	Nodes []Node `json:"nodes"`
	Edges []Edge `json:"edges"`
}

// AssistantResponse is the assistant's part of a conversation exchange.
type AssistantResponse struct {
	Response string   `json:"response"`
	Context  *Context `json:"context,omitempty"`
}

// Exchange is a single user/assistant turn in conversation history.
type Exchange struct {
	User      string            `json:"user"`
	Assistant AssistantResponse `json:"assistant"`
}

// --- Request types ---

type IngestRequest struct {
	Text  string   `json:"text"`
	Hints []string `json:"hints,omitempty"`
}

type RecallRequest struct {
	Question string   `json:"question"`
	Hints    []string `json:"hints,omitempty"`
}

type ConverseRequest struct {
	Message string     `json:"message"`
	History []Exchange `json:"history"`
}

// --- Response types ---

type IngestResponse struct {
	Summary string `json:"summary"`
}

type RecallResponse struct {
	Answer  string   `json:"answer"`
	Context *Context `json:"context,omitempty"`
}

type ConverseResponse struct {
	Response string   `json:"response"`
	Context  *Context `json:"context,omitempty"`
}

// Connection is a single edge + the node on the other end, returned by /graph/{id}.
type Connection struct {
	Edge Edge `json:"edge"`
	Node Node `json:"node"`
}

type GraphResponse struct {
	Node        Node         `json:"node"`
	Connections []Connection `json:"connections"`
}
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/types/ -v
```

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add client/internal/types/
git commit -m "feat(client): add shared types matching API contract"
```

---

### Task 3: HTTP Client

**Files:**
- Create: `client/internal/api/client.go`
- Create: `client/internal/api/client_test.go`

**Step 1: Write tests for all four endpoints**

`client/internal/api/client_test.go`:
```go
package api_test

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

func TestIngest(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/ingest" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		body, _ := io.ReadAll(r.Body)
		var req types.IngestRequest
		json.Unmarshal(body, &req)
		if req.Text != "test thought" {
			t.Errorf("got text %q", req.Text)
		}
		json.NewEncoder(w).Encode(types.IngestResponse{Summary: "Stored 1 note."})
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	resp, err := c.Ingest("test thought", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Summary != "Stored 1 note." {
		t.Errorf("got summary %q", resp.Summary)
	}
}

func TestRecall(t *testing.T) {
	ctx := &types.Context{
		Nodes: []types.Node{{ID: "note:1", Table: "note", Content: "GTD stuff"}},
		Edges: []types.Edge{},
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/recall" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		json.NewEncoder(w).Encode(types.RecallResponse{Answer: "You know about GTD.", Context: ctx})
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	resp, err := c.Recall("what do I know?", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Answer != "You know about GTD." {
		t.Errorf("got answer %q", resp.Answer)
	}
	if resp.Context == nil || len(resp.Context.Nodes) != 1 {
		t.Error("expected 1 node in context")
	}
}

func TestConverse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/converse" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		body, _ := io.ReadAll(r.Body)
		var req types.ConverseRequest
		json.Unmarshal(body, &req)
		if req.Message != "hello" {
			t.Errorf("got message %q", req.Message)
		}
		json.NewEncoder(w).Encode(types.ConverseResponse{Response: "Hi there."})
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	resp, err := c.Converse("hello", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Response != "Hi there." {
		t.Errorf("got response %q", resp.Response)
	}
}

func TestGraph(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/graph/note:abc" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		json.NewEncoder(w).Encode(types.GraphResponse{
			Node:        types.Node{ID: "note:abc", Table: "note", Content: "test"},
			Connections: []types.Connection{},
		})
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	resp, err := c.Graph("note:abc")
	if err != nil {
		t.Fatal(err)
	}
	if resp.Node.ID != "note:abc" {
		t.Errorf("got node ID %q", resp.Node.ID)
	}
}

func TestServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte("internal error"))
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	_, err := c.Recall("test", nil)
	if err == nil {
		t.Error("expected error for 500 response")
	}
}

func TestServerUnreachable(t *testing.T) {
	c := api.New("http://localhost:1") // nothing listening
	_, err := c.Recall("test", nil)
	if err == nil {
		t.Error("expected error for unreachable server")
	}
}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/api/ -v
```

Expected: FAIL — `api` package doesn't exist yet.

**Step 3: Implement HTTP client**

`client/internal/api/client.go`:
```go
package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"

	"second-brain-client/internal/types"
)

type Client struct {
	baseURL    string
	httpClient *http.Client
}

func New(baseURL string) *Client {
	return &Client{
		baseURL:    baseURL,
		httpClient: &http.Client{},
	}
}

func (c *Client) Ingest(text string, hints []string) (*types.IngestResponse, error) {
	req := types.IngestRequest{Text: text, Hints: hints}
	var resp types.IngestResponse
	if err := c.post("/ingest", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) Recall(question string, hints []string) (*types.RecallResponse, error) {
	req := types.RecallRequest{Question: question, Hints: hints}
	var resp types.RecallResponse
	if err := c.post("/recall", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) Converse(message string, history []types.Exchange) (*types.ConverseResponse, error) {
	if history == nil {
		history = []types.Exchange{}
	}
	req := types.ConverseRequest{Message: message, History: history}
	var resp types.ConverseResponse
	if err := c.post("/converse", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) Graph(id string) (*types.GraphResponse, error) {
	url := fmt.Sprintf("%s/graph/%s", c.baseURL, id)
	httpResp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer httpResp.Body.Close()
	if httpResp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(httpResp.Body)
		return nil, fmt.Errorf("server returned %d: %s", httpResp.StatusCode, body)
	}
	var resp types.GraphResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &resp, nil
}

func (c *Client) post(path string, reqBody any, respBody any) error {
	data, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("encode request: %w", err)
	}
	url := fmt.Sprintf("%s%s", c.baseURL, path)
	httpResp, err := c.httpClient.Post(url, "application/json", bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer httpResp.Body.Close()
	if httpResp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(httpResp.Body)
		return fmt.Errorf("server returned %d: %s", httpResp.StatusCode, body)
	}
	if err := json.NewDecoder(httpResp.Body).Decode(respBody); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	return nil
}
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/api/ -v
```

Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add client/internal/api/
git commit -m "feat(client): HTTP client for all API endpoints"
```

---

### Task 4: Cobra CLI — Command Mode

**Files:**
- Create: `client/cmd/brain/root.go`
- Create: `client/cmd/brain/ingest.go`
- Create: `client/cmd/brain/recall.go`
- Create: `client/cmd/brain/graph.go`
- Modify: `client/cmd/brain/main.go`
- Create: `client/cmd/brain/commands_test.go`

**Step 1: Write tests for command-mode subcommands**

`client/cmd/brain/commands_test.go`:
```go
package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"second-brain-client/internal/types"
)

func TestIngestCommand(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(types.IngestResponse{Summary: "Stored 1 note."})
	}))
	defer srv.Close()

	var buf bytes.Buffer
	cmd := newRootCmd()
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"ingest", "--server", srv.URL, "my test thought"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("Stored 1 note.")) {
		t.Errorf("output: %s", buf.String())
	}
}

func TestRecallCommand(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(types.RecallResponse{
			Answer:  "You know about GTD.",
			Context: &types.Context{Nodes: []types.Node{{ID: "note:1", Table: "note", Content: "GTD"}}, Edges: []types.Edge{}},
		})
	}))
	defer srv.Close()

	var buf bytes.Buffer
	cmd := newRootCmd()
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"recall", "--server", srv.URL, "what do I know?"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("You know about GTD.")) {
		t.Errorf("output: %s", buf.String())
	}
}

func TestGraphCommand(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(types.GraphResponse{
			Node:        types.Node{ID: "note:abc", Table: "note", Content: "test content"},
			Connections: []types.Connection{},
		})
	}))
	defer srv.Close()

	var buf bytes.Buffer
	cmd := newRootCmd()
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"graph", "--server", srv.URL, "note:abc"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("note:abc")) {
		t.Errorf("output: %s", buf.String())
	}
}

func TestRootNoArgsLaunchesTUI(t *testing.T) {
	// Just verify root command with no subcommand doesn't error
	// (actual TUI launch tested separately)
	cmd := newRootCmd()
	cmd.SetArgs([]string{"--help"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./cmd/brain/ -v
```

Expected: FAIL — `newRootCmd` doesn't exist.

**Step 3: Implement root command**

`client/cmd/brain/root.go`:
```go
package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

var serverURL string

func newRootCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "brain",
		Short: "Second Brain TUI client",
		Long:  "A terminal client for the Second Brain knowledge engine.",
		RunE: func(cmd *cobra.Command, args []string) error {
			// No subcommand = launch TUI (implemented in later task)
			fmt.Fprintln(cmd.OutOrStdout(), "TUI mode not yet implemented. Use a subcommand: ingest, recall, graph")
			return nil
		},
	}
	cmd.PersistentFlags().StringVar(&serverURL, "server", envOrDefault("BRAIN_SERVER_URL", "http://localhost:8000"), "server URL")
	cmd.AddCommand(newIngestCmd())
	cmd.AddCommand(newRecallCmd())
	cmd.AddCommand(newGraphCmd())
	return cmd
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
```

**Step 4: Implement ingest subcommand**

`client/cmd/brain/ingest.go`:
```go
package main

import (
	"fmt"
	"strings"

	"github.com/spf13/cobra"
	"second-brain-client/internal/api"
)

func newIngestCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "ingest [text]",
		Short: "Ingest a thought or piece of knowledge",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			text := strings.Join(args, " ")
			c := api.New(serverURL)
			resp, err := c.Ingest(text, nil)
			if err != nil {
				return fmt.Errorf("ingest failed: %w", err)
			}
			fmt.Fprintln(cmd.OutOrStdout(), resp.Summary)
			return nil
		},
	}
}
```

**Step 5: Implement recall subcommand**

`client/cmd/brain/recall.go`:
```go
package main

import (
	"fmt"
	"strings"

	"github.com/spf13/cobra"
	"second-brain-client/internal/api"
)

func newRecallCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "recall [question]",
		Short: "Ask the brain a question",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			question := strings.Join(args, " ")
			c := api.New(serverURL)
			resp, err := c.Recall(question, nil)
			if err != nil {
				return fmt.Errorf("recall failed: %w", err)
			}
			out := cmd.OutOrStdout()
			fmt.Fprintln(out, resp.Answer)
			if resp.Context != nil && len(resp.Context.Nodes) > 0 {
				fmt.Fprintf(out, "\n[%d nodes · %d edges]\n", len(resp.Context.Nodes), len(resp.Context.Edges))
			}
			return nil
		},
	}
}
```

**Step 6: Implement graph subcommand**

`client/cmd/brain/graph.go`:
```go
package main

import (
	"fmt"

	"github.com/spf13/cobra"
	"second-brain-client/internal/api"
)

func newGraphCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "graph [id]",
		Short: "Show a node and its connections",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c := api.New(serverURL)
			resp, err := c.Graph(args[0])
			if err != nil {
				return fmt.Errorf("graph failed: %w", err)
			}
			out := cmd.OutOrStdout()
			fmt.Fprintf(out, "[%s] %s\n", resp.Node.Table, nodeLabel(resp.Node))
			if len(resp.Connections) == 0 {
				fmt.Fprintln(out, "  (no connections)")
				return nil
			}
			for _, conn := range resp.Connections {
				fmt.Fprintf(out, "  ──%s──> [%s] %s\n", conn.Edge.Table, conn.Node.Table, nodeLabel(conn.Node))
			}
			return nil
		},
	}
}

func nodeLabel(n types.Node) string {
	if n.Name != "" {
		return n.Name
	}
	if n.Content != "" {
		if len(n.Content) > 60 {
			return n.Content[:57] + "..."
		}
		return n.Content
	}
	return n.ID
}
```

Note: add `"second-brain-client/internal/types"` to the imports in `graph.go` for the `types.Node` reference in `nodeLabel`.

**Step 7: Update main.go**

`client/cmd/brain/main.go`:
```go
package main

import "os"

func main() {
	if err := newRootCmd().Execute(); err != nil {
		os.Exit(1)
	}
}
```

**Step 8: Run tests to verify they pass**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./cmd/brain/ -v
```

Expected: PASS (4 tests)

**Step 9: Verify build and manual test**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go build -o brain ./cmd/brain
./brain --help
./brain ingest --help
./brain recall --help
./brain graph --help
```

**Step 10: Commit**

```bash
git add client/cmd/brain/
git commit -m "feat(client): command-mode CLI with ingest, recall, graph subcommands"
```

---

### Task 5: TUI Model and State

**Files:**
- Create: `client/internal/tui/model.go`
- Create: `client/internal/tui/messages.go`
- Create: `client/internal/tui/model_test.go`

**Step 1: Write tests for model state transitions**

`client/internal/tui/model_test.go`:
```go
package tui

import (
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	"second-brain-client/internal/types"
)

func TestInitialState(t *testing.T) {
	m := NewModel("http://localhost:8000")
	if m.focus != focusChat {
		t.Error("expected initial focus on chat")
	}
	if m.loading {
		t.Error("expected not loading initially")
	}
	if len(m.history) != 0 {
		t.Error("expected empty history")
	}
}

func TestTabSwitchesFocus(t *testing.T) {
	m := NewModel("http://localhost:8000")
	updated, _ := m.Update(tea.KeyMsg{Type: tea.KeyTab})
	model := updated.(Model)
	if model.focus != focusGraph {
		t.Error("expected focus on graph after tab")
	}
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyTab})
	model = updated.(Model)
	if model.focus != focusChat {
		t.Error("expected focus back on chat after second tab")
	}
}

func TestConverseResponseUpdatesState(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.loading = true
	ctx := &types.Context{
		Nodes: []types.Node{{ID: "note:1", Table: "note", Content: "test"}},
		Edges: []types.Edge{},
	}
	resp := converseResponseMsg{
		response: &types.ConverseResponse{Response: "Answer.", Context: ctx},
		userMsg:  "question?",
	}
	updated, _ := m.Update(resp)
	model := updated.(Model)
	if model.loading {
		t.Error("expected loading to be false after response")
	}
	if len(model.history) != 1 {
		t.Fatalf("expected 1 history entry, got %d", len(model.history))
	}
	if len(model.graph.Nodes) != 1 {
		t.Error("expected graph to be updated with context nodes")
	}
}

func TestConverseResponseWithoutContextPreservesGraph(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.graph = types.Context{
		Nodes: []types.Node{{ID: "note:old", Table: "note"}},
		Edges: []types.Edge{},
	}
	resp := converseResponseMsg{
		response: &types.ConverseResponse{Response: "Ingested.", Context: nil},
		userMsg:  "some thought",
	}
	updated, _ := m.Update(resp)
	model := updated.(Model)
	if len(model.graph.Nodes) != 1 || model.graph.Nodes[0].ID != "note:old" {
		t.Error("expected graph to be preserved when response has no context")
	}
}

func TestClearCommand(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.history = []types.Exchange{{User: "test", Assistant: types.AssistantResponse{Response: "resp"}}}
	m.graph = types.Context{Nodes: []types.Node{{ID: "note:1", Table: "note"}}, Edges: []types.Edge{}}
	m.context = &types.Context{Nodes: []types.Node{{ID: "note:1", Table: "note"}}, Edges: []types.Edge{}}

	updated, _ := m.Update(clearMsg{})
	model := updated.(Model)
	if len(model.history) != 0 {
		t.Error("expected history cleared")
	}
	if len(model.graph.Nodes) != 0 {
		t.Error("expected graph cleared")
	}
	if model.context != nil {
		t.Error("expected context cleared")
	}
}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v
```

Expected: FAIL — package doesn't exist.

**Step 3: Implement messages**

`client/internal/tui/messages.go`:
```go
package tui

import "second-brain-client/internal/types"

// converseResponseMsg is sent when /converse returns.
type converseResponseMsg struct {
	response *types.ConverseResponse
	userMsg  string
	err      error
}

// graphResponseMsg is sent when /graph/{id} returns (for node expansion).
type graphResponseMsg struct {
	response *types.GraphResponse
	err      error
}

// errorMsg wraps a generic error.
type errorMsg struct {
	err error
}

// clearMsg signals the user typed /clear.
type clearMsg struct{}
```

**Step 4: Implement model**

`client/internal/tui/model.go`:
```go
package tui

import (
	tea "github.com/charmbracelet/bubbletea"
	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

type focus int

const (
	focusChat focus = iota
	focusGraph
)

const maxHistory = 10

type Model struct {
	client  *api.Client
	history []types.Exchange
	context *types.Context         // curated context from last recall
	graph   types.Context          // currently displayed graph (may diverge after expansion)
	focus   focus
	loading bool
	err     error
	width   int
	height  int

	// chat display
	messages []chatMessage
}

type chatMessage struct {
	role string // "user" or "brain"
	text string
}

func NewModel(serverURL string) Model {
	return Model{
		client:   api.New(serverURL),
		history:  []types.Exchange{},
		graph:    types.Context{},
		messages: []chatMessage{},
		focus:    focusChat,
	}
}

func (m Model) Init() tea.Cmd {
	return nil
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyCtrlC:
			return m, tea.Quit
		case tea.KeyTab:
			if m.focus == focusChat {
				m.focus = focusGraph
			} else {
				m.focus = focusChat
			}
			return m, nil
		}

	case converseResponseMsg:
		m.loading = false
		if msg.err != nil {
			m.err = msg.err
			m.messages = append(m.messages, chatMessage{role: "brain", text: "Error: " + msg.err.Error()})
			return m, nil
		}
		m.messages = append(m.messages, chatMessage{role: "brain", text: msg.response.Response})
		exchange := types.Exchange{
			User: msg.userMsg,
			Assistant: types.AssistantResponse{
				Response: msg.response.Response,
				Context:  msg.response.Context,
			},
		}
		m.history = append(m.history, exchange)
		if len(m.history) > maxHistory {
			m.history = m.history[len(m.history)-maxHistory:]
		}
		if msg.response.Context != nil {
			m.context = msg.response.Context
			m.graph = *msg.response.Context
		}
		return m, nil

	case graphResponseMsg:
		if msg.err != nil {
			m.err = msg.err
			return m, nil
		}
		// Merge expanded connections into the graph
		for _, conn := range msg.response.Connections {
			if !containsNode(m.graph.Nodes, conn.Node.ID) {
				m.graph.Nodes = append(m.graph.Nodes, conn.Node)
			}
			if !containsEdge(m.graph.Edges, conn.Edge.ID) {
				m.graph.Edges = append(m.graph.Edges, conn.Edge)
			}
		}
		return m, nil

	case clearMsg:
		m.history = []types.Exchange{}
		m.context = nil
		m.graph = types.Context{}
		m.messages = []chatMessage{}
		m.err = nil
		return m, nil

	case errorMsg:
		m.err = msg.err
		return m, nil
	}

	return m, nil
}

func (m Model) View() string {
	// Placeholder — implemented in Task 8
	return "brain TUI"
}

func containsNode(nodes []types.Node, id string) bool {
	for _, n := range nodes {
		if n.ID == id {
			return true
		}
	}
	return false
}

func containsEdge(edges []types.Edge, id string) bool {
	for _, e := range edges {
		if e.ID == id {
			return true
		}
	}
	return false
}
```

**Step 5: Run tests to verify they pass**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v
```

Expected: PASS (5 tests)

**Step 6: Commit**

```bash
git add client/internal/tui/
git commit -m "feat(client): TUI model with state transitions and message types"
```

---

### Task 6: Chat Panel

**Files:**
- Create: `client/internal/tui/chat.go`
- Create: `client/internal/tui/chat_test.go`
- Modify: `client/internal/tui/model.go`

**Step 1: Write tests for chat panel rendering**

`client/internal/tui/chat_test.go`:
```go
package tui

import (
	"strings"
	"testing"
)

func TestRenderChatEmpty(t *testing.T) {
	c := newChatPanel(40, 10)
	view := c.View()
	if view == "" {
		t.Error("expected non-empty view for empty chat")
	}
}

func TestRenderChatWithMessages(t *testing.T) {
	c := newChatPanel(40, 10)
	c.addMessage("user", "Hello brain")
	c.addMessage("brain", "Hello human")
	view := c.View()
	if !strings.Contains(view, "Hello brain") {
		t.Error("expected user message in view")
	}
	if !strings.Contains(view, "Hello human") {
		t.Error("expected brain message in view")
	}
}

func TestRenderChatLoading(t *testing.T) {
	c := newChatPanel(40, 10)
	c.loading = true
	view := c.View()
	// Should contain some loading indicator
	if view == "" {
		t.Error("expected non-empty view when loading")
	}
}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v -run TestRenderChat
```

Expected: FAIL — `newChatPanel` doesn't exist.

**Step 3: Implement chat panel**

`client/internal/tui/chat.go`:
```go
package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"
)

var (
	userStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
	brainStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("5")).Bold(true)
)

type chatPanel struct {
	messages []chatMessage
	viewport viewport.Model
	loading  bool
	width    int
	height   int
}

func newChatPanel(width, height int) chatPanel {
	vp := viewport.New(width, height)
	return chatPanel{
		messages: []chatMessage{},
		viewport: vp,
		width:    width,
		height:   height,
	}
}

func (c *chatPanel) addMessage(role, text string) {
	c.messages = append(c.messages, chatMessage{role: role, text: text})
	c.viewport.SetContent(c.renderMessages())
	c.viewport.GotoBottom()
}

func (c *chatPanel) setSize(width, height int) {
	c.width = width
	c.height = height
	c.viewport.Width = width
	c.viewport.Height = height
	c.viewport.SetContent(c.renderMessages())
}

func (c chatPanel) renderMessages() string {
	if len(c.messages) == 0 {
		return lipgloss.NewStyle().
			Faint(true).
			Render("Type a message to start...")
	}
	var b strings.Builder
	for _, msg := range c.messages {
		var label string
		if msg.role == "user" {
			label = userStyle.Render("You: ")
		} else {
			label = brainStyle.Render("Brain: ")
		}
		b.WriteString(fmt.Sprintf("\n%s%s\n", label, msg.text))
	}
	if c.loading {
		b.WriteString(fmt.Sprintf("\n%s\n", brainStyle.Render("Thinking...")))
	}
	return b.String()
}

func (c chatPanel) View() string {
	return c.viewport.View()
}
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v -run TestRenderChat
```

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add client/internal/tui/chat.go client/internal/tui/chat_test.go
git commit -m "feat(client): chat panel with message rendering and viewport scrolling"
```

---

### Task 7: Graph Panel

**Files:**
- Create: `client/internal/tui/graph.go`
- Create: `client/internal/tui/graph_test.go`

**Step 1: Write tests for graph panel state and rendering**

`client/internal/tui/graph_test.go`:
```go
package tui

import (
	"strings"
	"testing"

	"second-brain-client/internal/types"
)

func TestGraphPanelEmpty(t *testing.T) {
	g := newGraphPanel(30, 10)
	view := g.View()
	if !strings.Contains(view, "No graph") {
		t.Errorf("expected empty state message, got: %s", view)
	}
}

func TestGraphPanelWithNodes(t *testing.T) {
	g := newGraphPanel(30, 10)
	g.setContext(types.Context{
		Nodes: []types.Node{
			{ID: "entity:1", Table: "entity", Name: "GTD"},
			{ID: "entity:2", Table: "entity", Name: "Agile"},
		},
		Edges: []types.Edge{
			{ID: "relates_to:1", Table: "relates_to", From: "entity:1", To: "entity:2"},
		},
	})
	view := g.View()
	if !strings.Contains(view, "GTD") {
		t.Error("expected GTD in view")
	}
	if !strings.Contains(view, "Agile") {
		t.Error("expected Agile in view")
	}
}

func TestGraphPanelNavigation(t *testing.T) {
	g := newGraphPanel(30, 10)
	g.setContext(types.Context{
		Nodes: []types.Node{
			{ID: "entity:1", Table: "entity", Name: "GTD"},
			{ID: "entity:2", Table: "entity", Name: "Agile"},
			{ID: "entity:3", Table: "entity", Name: "Scrum"},
		},
		Edges: []types.Edge{},
	})
	if g.cursor != 0 {
		t.Error("expected cursor at 0")
	}
	g.moveDown()
	if g.cursor != 1 {
		t.Errorf("expected cursor at 1, got %d", g.cursor)
	}
	g.moveDown()
	g.moveDown() // should not go past last item
	if g.cursor != 2 {
		t.Errorf("expected cursor at 2, got %d", g.cursor)
	}
	g.moveUp()
	if g.cursor != 1 {
		t.Errorf("expected cursor at 1, got %d", g.cursor)
	}
}

func TestGraphPanelSelectedNode(t *testing.T) {
	g := newGraphPanel(30, 10)
	g.setContext(types.Context{
		Nodes: []types.Node{
			{ID: "entity:1", Table: "entity", Name: "GTD"},
			{ID: "entity:2", Table: "entity", Name: "Agile"},
		},
		Edges: []types.Edge{},
	})
	g.moveDown()
	node := g.selectedNode()
	if node == nil || node.ID != "entity:2" {
		t.Errorf("expected entity:2, got %v", node)
	}
}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v -run TestGraphPanel
```

Expected: FAIL — `newGraphPanel` doesn't exist.

**Step 3: Implement graph panel**

`client/internal/tui/graph.go`:
```go
package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"second-brain-client/internal/types"
)

var (
	nodeEntityStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("3"))
	nodeNoteStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("4"))
	edgeStyle       = lipgloss.NewStyle().Faint(true)
	selectedStyle   = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("2"))
)

type graphPanel struct {
	nodes  []types.Node
	edges  []types.Edge
	cursor int
	width  int
	height int
}

func newGraphPanel(width, height int) graphPanel {
	return graphPanel{
		width:  width,
		height: height,
	}
}

func (g *graphPanel) setContext(ctx types.Context) {
	g.nodes = ctx.Nodes
	g.edges = ctx.Edges
	g.cursor = 0
}

func (g *graphPanel) setSize(width, height int) {
	g.width = width
	g.height = height
}

func (g *graphPanel) moveDown() {
	if g.cursor < len(g.nodes)-1 {
		g.cursor++
	}
}

func (g *graphPanel) moveUp() {
	if g.cursor > 0 {
		g.cursor--
	}
}

func (g *graphPanel) selectedNode() *types.Node {
	if len(g.nodes) == 0 {
		return nil
	}
	return &g.nodes[g.cursor]
}

func (g graphPanel) View() string {
	if len(g.nodes) == 0 {
		return lipgloss.NewStyle().Faint(true).Render("No graph context")
	}
	var b strings.Builder
	b.WriteString("Nodes:\n")
	for i, n := range g.nodes {
		prefix := "  "
		if i == g.cursor {
			prefix = "> "
		}
		label := nodeLabel(n)
		tag := fmt.Sprintf("[%s]", n.Table)
		var line string
		if i == g.cursor {
			line = selectedStyle.Render(fmt.Sprintf("%s%s %s", prefix, tag, label))
		} else {
			style := nodeNoteStyle
			if n.Table == "entity" {
				style = nodeEntityStyle
			}
			line = fmt.Sprintf("%s%s %s", prefix, style.Render(tag), label)
		}
		b.WriteString(line + "\n")
	}
	if len(g.edges) > 0 {
		b.WriteString("\nEdges:\n")
		for _, e := range g.edges {
			fromLabel := g.findNodeLabel(e.From)
			toLabel := g.findNodeLabel(e.To)
			line := edgeStyle.Render(fmt.Sprintf("  %s ──%s──> %s", fromLabel, e.Table, toLabel))
			b.WriteString(line + "\n")
		}
	}
	return b.String()
}

func (g graphPanel) findNodeLabel(id string) string {
	for _, n := range g.nodes {
		if n.ID == id {
			return nodeLabel(n)
		}
	}
	return id
}
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v -run TestGraphPanel
```

Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add client/internal/tui/graph.go client/internal/tui/graph_test.go
git commit -m "feat(client): graph panel with node/edge rendering and keyboard navigation"
```

---

### Task 8: Input Bar with @ Autocomplete

**Files:**
- Create: `client/internal/tui/input.go`
- Create: `client/internal/tui/input_test.go`

**Step 1: Write tests for @ autocomplete**

`client/internal/tui/input_test.go`:
```go
package tui

import (
	"testing"

	"second-brain-client/internal/types"
)

func TestExtractAtQuery(t *testing.T) {
	tests := []struct {
		input string
		want  string
		found bool
	}{
		{"hello @GTD", "GTD", true},
		{"@Ag", "Ag", true},
		{"no mention", "", false},
		{"@", "", true},
		{"tell me about @Productivity and", "", false}, // @ not at end
	}
	for _, tt := range tests {
		got, found := extractAtQuery(tt.input)
		if found != tt.found || got != tt.want {
			t.Errorf("extractAtQuery(%q) = (%q, %v), want (%q, %v)", tt.input, got, found, tt.want, tt.found)
		}
	}
}

func TestFilterSuggestions(t *testing.T) {
	nodes := []types.Node{
		{ID: "entity:1", Table: "entity", Name: "GTD"},
		{ID: "entity:2", Table: "entity", Name: "Agile"},
		{ID: "entity:3", Table: "entity", Name: "Scrum"},
		{ID: "note:1", Table: "note", Content: "Getting things done overview"},
	}
	suggestions := filterSuggestions(nodes, "G")
	if len(suggestions) != 2 { // GTD and "Getting things done..."
		t.Errorf("expected 2 suggestions, got %d", len(suggestions))
	}
	suggestions = filterSuggestions(nodes, "")
	if len(suggestions) != 4 {
		t.Errorf("expected 4 suggestions for empty query, got %d", len(suggestions))
	}
}

func TestResolveAtReferences(t *testing.T) {
	nodes := []types.Node{
		{ID: "entity:1", Table: "entity", Name: "GTD"},
		{ID: "entity:2", Table: "entity", Name: "Agile"},
	}
	text, ids := resolveAtReferences("Tell me about @GTD and @Agile", nodes)
	if text != "Tell me about GTD and Agile" {
		t.Errorf("got text %q", text)
	}
	if len(ids) != 2 {
		t.Errorf("expected 2 resolved IDs, got %d", len(ids))
	}
}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v -run "TestExtractAt|TestFilter|TestResolve"
```

Expected: FAIL — functions don't exist.

**Step 3: Implement input with @ logic**

`client/internal/tui/input.go`:
```go
package tui

import (
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	"second-brain-client/internal/types"
)

type inputBar struct {
	textInput   textinput.Model
	suggestions []suggestion
	showSuggest bool
	suggestIdx  int
}

type suggestion struct {
	label string
	node  types.Node
}

func newInputBar() inputBar {
	ti := textinput.New()
	ti.Placeholder = "Type a message..."
	ti.Focus()
	return inputBar{textInput: ti}
}

// extractAtQuery returns the text after the last @ if it's at the end of the input
// (i.e., the user is currently typing an @ reference).
func extractAtQuery(input string) (string, bool) {
	idx := strings.LastIndex(input, "@")
	if idx == -1 {
		return "", false
	}
	after := input[idx+1:]
	// Only active if @ is at or near the end (no space after the query)
	if strings.Contains(after, " ") {
		return "", false
	}
	return after, true
}

// filterSuggestions returns nodes whose name or content prefix-matches the query (case-insensitive).
func filterSuggestions(nodes []types.Node, query string) []suggestion {
	query = strings.ToLower(query)
	var results []suggestion
	for _, n := range nodes {
		label := nodeLabel(n)
		if query == "" || strings.Contains(strings.ToLower(label), query) {
			results = append(results, suggestion{label: label, node: n})
		}
	}
	return results
}

// resolveAtReferences replaces @Name references in text with the plain name,
// and returns the list of resolved node IDs.
func resolveAtReferences(text string, nodes []types.Node) (string, []string) {
	var ids []string
	result := text
	for _, n := range nodes {
		label := nodeLabel(n)
		ref := "@" + label
		if strings.Contains(result, ref) {
			result = strings.ReplaceAll(result, ref, label)
			ids = append(ids, n.ID)
		}
	}
	return result, ids
}
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v -run "TestExtractAt|TestFilter|TestResolve"
```

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add client/internal/tui/input.go client/internal/tui/input_test.go
git commit -m "feat(client): input bar with @ autocomplete and node reference resolution"
```

---

### Task 9: Split-Pane Layout and View Rendering

**Files:**
- Create: `client/internal/tui/view.go`
- Modify: `client/internal/tui/model.go` — integrate chat, graph, input panels into model
- Modify: `client/internal/tui/model_test.go` — add view rendering tests

The View in Bubble Tea returns a single string. This task composes the chat panel, graph panel, and input bar into a split-pane layout using Lip Gloss.

**Step 1: Write tests for view rendering**

Add to `client/internal/tui/model_test.go`:
```go
func TestViewContainsPanels(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.width = 80
	m.height = 24
	m.initPanels()
	m.chat.addMessage("user", "Hello")
	m.chat.addMessage("brain", "Hi there")
	m.graph.setContext(types.Context{
		Nodes: []types.Node{{ID: "entity:1", Table: "entity", Name: "GTD"}},
		Edges: []types.Edge{},
	})
	view := m.View()
	if view == "" {
		t.Error("expected non-empty view")
	}
	// View should contain content from both panels
	if !strings.Contains(view, "Hello") {
		t.Error("expected chat content in view")
	}
	if !strings.Contains(view, "GTD") {
		t.Error("expected graph content in view")
	}
}
```

Add `"strings"` to the test file imports.

**Step 2: Run test to verify it fails**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v -run TestViewContainsPanels
```

Expected: FAIL — `initPanels`, `chat`, `graph` fields don't exist on Model.

**Step 3: Implement view.go with layout logic**

`client/internal/tui/view.go`:
```go
package tui

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
)

var (
	headerStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("7")).
			Background(lipgloss.Color("5")).
			Padding(0, 1)

	panelBorder = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("8"))

	focusedBorder = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("5"))

	statusStyle = lipgloss.NewStyle().
			Faint(true)
)

func (m Model) renderView() string {
	if m.width == 0 || m.height == 0 {
		return "Initializing..."
	}

	// Header
	header := headerStyle.Width(m.width).Render("second-brain")

	// Calculate panel dimensions
	// Reserve: 1 header + 2 border + 1 input + 2 input border + 1 status = ~7 lines overhead
	inputHeight := 1
	statusHeight := 1
	headerHeight := 1
	borderOverhead := 4 // 2 per panel (top+bottom border)
	panelHeight := m.height - headerHeight - inputHeight - statusHeight - borderOverhead
	if panelHeight < 3 {
		panelHeight = 3
	}

	chatWidth := m.width*3/5 - 3 // 60% minus border padding
	graphWidth := m.width - chatWidth - 5 // remaining minus borders

	// Resize panels
	m.chat.setSize(chatWidth, panelHeight)
	m.graphPanel.setSize(graphWidth, panelHeight)

	// Render panels with borders
	chatBorder := panelBorder
	graphBorderStyle := panelBorder
	if m.focus == focusChat {
		chatBorder = focusedBorder
	} else {
		graphBorderStyle = focusedBorder
	}

	chatView := chatBorder.
		Width(chatWidth).
		Height(panelHeight).
		Render(m.chat.View())

	graphView := graphBorderStyle.
		Width(graphWidth).
		Height(panelHeight).
		Render(m.graphPanel.View())

	// Side by side
	panels := lipgloss.JoinHorizontal(lipgloss.Top, chatView, graphView)

	// Input bar
	inputView := m.input.textInput.View()

	// Status line
	status := statusStyle.Render(fmt.Sprintf("TAB switch focus · /clear reset · /quit exit · %d nodes · %d edges",
		len(m.graphPanel.nodes), len(m.graphPanel.edges)))

	return lipgloss.JoinVertical(lipgloss.Left, header, panels, inputView, status)
}
```

**Step 4: Update model.go to integrate panels**

Update `Model` struct and methods in `client/internal/tui/model.go` to include panel fields:

Add fields to `Model` struct:
```go
	// panels
	chat       chatPanel
	graphPanel graphPanel
	input      inputBar
```

Add `initPanels` method:
```go
func (m *Model) initPanels() {
	m.chat = newChatPanel(40, 10)
	m.graphPanel = newGraphPanel(30, 10)
	m.input = newInputBar()
}
```

Update `NewModel` to call `initPanels`:
```go
func NewModel(serverURL string) Model {
	m := Model{
		client:  api.New(serverURL),
		history: []types.Exchange{},
		graph:   types.Context{},
		focus:   focusChat,
	}
	m.initPanels()
	return m
}
```

Remove the standalone `messages []chatMessage` field from the struct (replaced by `chat.messages`).

Update `View()` to call `renderView()`:
```go
func (m Model) View() string {
	return m.renderView()
}
```

Update `converseResponseMsg` handler to use `m.chat.addMessage` instead of appending to `m.messages`:
```go
	case converseResponseMsg:
		m.loading = false
		m.chat.loading = false
		if msg.err != nil {
			m.err = msg.err
			m.chat.addMessage("brain", "Error: "+msg.err.Error())
			return m, nil
		}
		m.chat.addMessage("brain", msg.response.Response)
		// ... rest unchanged
```

Update `graphResponseMsg` handler to also update `m.graphPanel`:
```go
	case graphResponseMsg:
		if msg.err != nil {
			m.err = msg.err
			return m, nil
		}
		for _, conn := range msg.response.Connections {
			if !containsNode(m.graph.Nodes, conn.Node.ID) {
				m.graph.Nodes = append(m.graph.Nodes, conn.Node)
			}
			if !containsEdge(m.graph.Edges, conn.Edge.ID) {
				m.graph.Edges = append(m.graph.Edges, conn.Edge)
			}
		}
		m.graphPanel.setContext(m.graph)
		return m, nil
```

Update `clearMsg` handler:
```go
	case clearMsg:
		m.history = []types.Exchange{}
		m.context = nil
		m.graph = types.Context{}
		m.chat = newChatPanel(m.chat.width, m.chat.height)
		m.graphPanel.setContext(types.Context{})
		m.err = nil
		return m, nil
```

**Step 5: Run all TUI tests**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v
```

Expected: PASS (all tests)

**Step 6: Commit**

```bash
git add client/internal/tui/
git commit -m "feat(client): split-pane layout with lipgloss, integrate chat and graph panels"
```

---

### Task 10: Full Update Logic — Keyboard Handling and Commands

**Files:**
- Create: `client/internal/tui/update.go`
- Modify: `client/internal/tui/model.go` — move Update logic to update.go
- Modify: `client/internal/tui/model_test.go` — add input submission tests

This task wires up: text input handling, Enter to submit, `/clear` and `/quit` commands, `@` autocomplete interaction, graph panel keyboard navigation, and async HTTP calls via `tea.Cmd`.

**Step 1: Write tests for input submission and command handling**

Add to `client/internal/tui/model_test.go`:
```go
func TestSubmitSendsConverse(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.width = 80
	m.height = 24
	// Simulate typing and submitting
	m.input.textInput.SetValue("What do I know about GTD?")
	updated, cmd := m.submitInput()
	model := updated
	if !model.loading {
		t.Error("expected loading after submit")
	}
	if cmd == nil {
		t.Error("expected a command for the HTTP call")
	}
	if model.input.textInput.Value() != "" {
		t.Error("expected input cleared after submit")
	}
}

func TestSubmitClearCommand(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.width = 80
	m.height = 24
	m.history = []types.Exchange{{User: "q", Assistant: types.AssistantResponse{Response: "a"}}}
	m.input.textInput.SetValue("/clear")
	updated, _ := m.submitInput()
	model := updated
	if len(model.history) != 0 {
		t.Error("expected history cleared after /clear")
	}
}

func TestSubmitQuitCommand(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.input.textInput.SetValue("/quit")
	_, cmd := m.submitInput()
	// cmd should be tea.Quit
	if cmd == nil {
		t.Error("expected quit command")
	}
}

func TestGraphPanelKeysWhenFocused(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.focus = focusGraph
	m.graphPanel.setContext(types.Context{
		Nodes: []types.Node{
			{ID: "entity:1", Table: "entity", Name: "GTD"},
			{ID: "entity:2", Table: "entity", Name: "Agile"},
		},
		Edges: []types.Edge{},
	})
	// Down arrow
	updated, _ := m.Update(tea.KeyMsg{Type: tea.KeyDown})
	model := updated.(Model)
	if model.graphPanel.cursor != 1 {
		t.Errorf("expected cursor at 1, got %d", model.graphPanel.cursor)
	}
	// Up arrow
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyUp})
	model = updated.(Model)
	if model.graphPanel.cursor != 0 {
		t.Errorf("expected cursor at 0, got %d", model.graphPanel.cursor)
	}
}
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v -run "TestSubmit|TestGraphPanelKeys"
```

Expected: FAIL — `submitInput` doesn't exist.

**Step 3: Implement update.go**

`client/internal/tui/update.go`:
```go
package tui

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

// submitInput processes the current input value.
func (m *Model) submitInput() (Model, tea.Cmd) {
	value := strings.TrimSpace(m.input.textInput.Value())
	m.input.textInput.SetValue("")
	m.input.showSuggest = false

	if value == "" {
		return *m, nil
	}

	// Handle commands
	switch {
	case value == "/quit":
		return *m, tea.Quit
	case value == "/clear":
		m.history = []types.Exchange{}
		m.context = nil
		m.graph = types.Context{}
		m.chat = newChatPanel(m.chat.width, m.chat.height)
		m.graphPanel.setContext(types.Context{})
		m.err = nil
		return *m, nil
	case value == "/graph":
		m.focus = focusGraph
		return *m, nil
	}

	// Resolve @ references
	resolvedText, hintIDs := resolveAtReferences(value, m.graphPanel.nodes)

	// Add user message to chat
	m.chat.addMessage("user", value)
	m.loading = true
	m.chat.loading = true

	// Build history with any hint IDs from @ references
	history := m.history
	_ = hintIDs // hints are passed via /converse message context in future API

	// Send converse request
	return *m, m.sendConverse(resolvedText, history)
}

// sendConverse returns a tea.Cmd that calls /converse asynchronously.
func (m *Model) sendConverse(message string, history []types.Exchange) tea.Cmd {
	client := m.client
	return func() tea.Msg {
		resp, err := client.Converse(message, history)
		if err != nil {
			return converseResponseMsg{err: err, userMsg: message}
		}
		return converseResponseMsg{response: resp, userMsg: message}
	}
}

// sendGraphExpand returns a tea.Cmd that calls /graph/{id} asynchronously.
func (m *Model) sendGraphExpand(id string) tea.Cmd {
	client := m.client
	return func() tea.Msg {
		resp, err := client.Graph(id)
		if err != nil {
			return graphResponseMsg{err: err}
		}
		return graphResponseMsg{response: resp}
	}
}
```

**Step 4: Update model.go Update method to use the new logic**

Replace the `tea.KeyMsg` handling in `model.go`'s `Update` method:
```go
	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyCtrlC:
			return m, tea.Quit
		case tea.KeyTab:
			if m.focus == focusChat {
				m.focus = focusGraph
			} else {
				m.focus = focusChat
			}
			return m, nil
		case tea.KeyEnter:
			if m.focus == focusChat && !m.loading {
				updated, cmd := m.submitInput()
				return updated, cmd
			}
			if m.focus == focusGraph {
				if node := m.graphPanel.selectedNode(); node != nil {
					return m, m.sendGraphExpand(node.ID)
				}
			}
			return m, nil
		case tea.KeyUp:
			if m.focus == focusGraph {
				m.graphPanel.moveUp()
				return m, nil
			}
		case tea.KeyDown:
			if m.focus == focusGraph {
				m.graphPanel.moveDown()
				return m, nil
			}
		case tea.KeyEsc:
			if m.focus == focusGraph {
				m.focus = focusChat
				return m, nil
			}
		}
		// Forward key to text input when chat is focused
		if m.focus == focusChat {
			var cmd tea.Cmd
			m.input.textInput, cmd = m.input.textInput.Update(msg)
			// Update autocomplete suggestions
			if query, found := extractAtQuery(m.input.textInput.Value()); found {
				m.input.suggestions = filterSuggestions(m.graphPanel.nodes, query)
				m.input.showSuggest = len(m.input.suggestions) > 0
			} else {
				m.input.showSuggest = false
			}
			return m, cmd
		}
```

**Step 5: Run all tests**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./internal/tui/ -v
```

Expected: PASS (all tests)

**Step 6: Commit**

```bash
git add client/internal/tui/
git commit -m "feat(client): keyboard handling, input submission, /clear /quit /graph commands"
```

---

### Task 11: Wire TUI into Cobra Root Command

**Files:**
- Modify: `client/cmd/brain/root.go`
- Modify: `client/cmd/brain/main.go`

**Step 1: Update root command to launch TUI when no subcommand given**

Update `root.go` `RunE` function:
```go
		RunE: func(cmd *cobra.Command, args []string) error {
			m := tui.NewModel(serverURL)
			p := tea.NewProgram(m, tea.WithAltScreen())
			if _, err := p.Run(); err != nil {
				return fmt.Errorf("TUI error: %w", err)
			}
			return nil
		},
```

Add import: `"second-brain-client/internal/tui"` and `tea "github.com/charmbracelet/bubbletea"`.

**Step 2: Build and manual test**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go build -o brain ./cmd/brain
```

Verify:
- `./brain --help` shows usage with subcommands
- `./brain ingest --help` shows ingest usage
- `./brain recall --help` shows recall usage
- `./brain` launches the TUI (will show split pane, Ctrl+C to exit)

**Step 3: Run all tests**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./... -v
```

Expected: PASS (all packages)

**Step 4: Commit**

```bash
git add client/
git commit -m "feat(client): wire TUI into root command, complete client v1"
```

---

### Task 12: Final Cleanup and Integration Verification

**Files:**
- Modify: `client/cmd/brain/graph.go` — ensure `nodeLabel` uses types package (avoid duplicate)
- Review all files for unused imports

**Step 1: Move shared `nodeLabel` function to types package**

The `nodeLabel` function is used in both `cmd/brain/graph.go` and `internal/tui/graph.go`. Move it to `types.go`:

Add to `client/internal/types/types.go`:
```go
// NodeLabel returns a human-readable label for a node.
func NodeLabel(n Node) string {
	if n.Name != "" {
		return n.Name
	}
	if n.Content != "" {
		if len(n.Content) > 60 {
			return n.Content[:57] + "..."
		}
		return n.Content
	}
	return n.ID
}
```

Update `cmd/brain/graph.go` to use `types.NodeLabel(n)` instead of local `nodeLabel(n)`.
Update `internal/tui/graph.go` to use `types.NodeLabel(n)` instead of local `nodeLabel(n)`.
Update `internal/tui/input.go` to use `types.NodeLabel(n)` instead of local `nodeLabel(n)`.
Remove all local `nodeLabel` functions.

**Step 2: Run all tests**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go test ./... -v
```

Expected: PASS

**Step 3: Build final binary**

```bash
cd /Users/antoinelennartz/Source/Repos/second-brain/client
go build -o brain ./cmd/brain
```

**Step 4: Commit**

```bash
git add client/
git commit -m "refactor(client): extract shared NodeLabel, final cleanup"
```

---

## Server-Side Changes Needed

The following changes are needed on the server to fully support this client. These are **not part of this plan** (another agent handles the server) but are documented for coordination:

1. **Remove `source` field from `IngestRequest`** — design decision from brainstorming
2. **Add `hints` field to `IngestRequest` and `RecallRequest`** — optional `list[str]` of node IDs
3. **Add `context` to `RecallResponse`** — `{nodes: [...], edges: [...]}` curated by the agent
4. **Add `POST /converse` endpoint** — conversation agent with ingest/recall as tools, accepts `{message, history[]}`, returns `{response, context?}`
5. **Remove `GET /notes` and `GET /entities`** — not needed
6. **Update recall agent** to specify relevant node/edge IDs in its answer tool call

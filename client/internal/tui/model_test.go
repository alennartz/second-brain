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

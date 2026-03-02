package tui

import (
	"errors"
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

func TestConverseResponseClearsError(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.err = errors.New("previous error")
	resp := converseResponseMsg{
		response: &types.ConverseResponse{Response: "OK.", Context: nil},
		userMsg:  "test",
	}
	updated, _ := m.Update(resp)
	model := updated.(Model)
	if model.err != nil {
		t.Error("expected err to be cleared after successful converse response")
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

func TestSubmitSendsConverse(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.width = 80
	m.height = 24
	m.input.textArea.SetValue("What do I know about GTD?")
	updated, cmd := m.submitInput()
	model := updated
	if !model.loading {
		t.Error("expected loading after submit")
	}
	if cmd == nil {
		t.Error("expected a command for the HTTP call")
	}
	if model.input.textArea.Value() != "" {
		t.Error("expected input cleared after submit")
	}
}

func TestSubmitClearCommand(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.width = 80
	m.height = 24
	m.history = []types.Exchange{{User: "q", Assistant: types.AssistantResponse{Response: "a"}}}
	m.input.textArea.SetValue("/clear")
	updated, cmd := m.submitInput()
	if cmd == nil {
		t.Fatal("expected a command from /clear")
	}
	// Execute the returned command and pass result through Update
	msg := cmd()
	result, _ := updated.Update(msg)
	model := result.(Model)
	if len(model.history) != 0 {
		t.Error("expected history cleared after /clear")
	}
}

func TestSubmitQuitCommand(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.input.textArea.SetValue("/exit")
	_, cmd := m.submitInput()
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
	updated, _ := m.Update(tea.KeyMsg{Type: tea.KeyDown})
	model := updated.(Model)
	if model.graphPanel.cursor != 1 {
		t.Errorf("expected cursor at 1, got %d", model.graphPanel.cursor)
	}
	updated, _ = model.Update(tea.KeyMsg{Type: tea.KeyUp})
	model = updated.(Model)
	if model.graphPanel.cursor != 0 {
		t.Errorf("expected cursor at 0, got %d", model.graphPanel.cursor)
	}
}

func TestViewContainsPanels(t *testing.T) {
	m := NewModel("http://localhost:8000")
	// Send WindowSizeMsg through Update so panels get sized
	updated, _ := m.Update(tea.WindowSizeMsg{Width: 80, Height: 24})
	m = updated.(Model)
	m.chat.addMessage("user", "Hello")
	m.chat.addMessage("brain", "Hi there")
	m.graphPanel.setContext(types.Context{
		Nodes: []types.Node{{ID: "entity:1", Table: "entity", Name: "GTD"}},
		Edges: []types.Edge{},
	})
	view := m.View()
	if view == "" {
		t.Error("expected non-empty view")
	}
}

func TestEscSwitchesToChat(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.focus = focusGraph
	updated, _ := m.Update(tea.KeyMsg{Type: tea.KeyEsc})
	model := updated.(Model)
	if model.focus != focusChat {
		t.Error("expected focus on chat after Esc")
	}
}

func TestEnterInGraphExpandsNode(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.focus = focusGraph
	m.graphPanel.setContext(types.Context{
		Nodes: []types.Node{
			{ID: "entity:1", Table: "entity", Name: "GTD"},
		},
		Edges: []types.Edge{},
	})
	_, cmd := m.Update(tea.KeyMsg{Type: tea.KeyEnter})
	if cmd == nil {
		t.Error("expected a command for graph expansion")
	}
}

func TestSubmitEmptyDoesNothing(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.input.textArea.SetValue("")
	updated, cmd := m.submitInput()
	if cmd != nil {
		t.Error("expected nil command for empty input")
	}
	if updated.loading {
		t.Error("expected not loading for empty input")
	}
}

func TestSlashGraphSwitchesFocus(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.input.textArea.SetValue("/graph")
	updated, _ := m.submitInput()
	if updated.focus != focusGraph {
		t.Error("expected focus on graph after /graph command")
	}
}

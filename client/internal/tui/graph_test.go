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
			{ID: "relates_to:1", Table: "relates_to", Out: "entity:1", In: "entity:2"},
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
	g.moveDown()
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

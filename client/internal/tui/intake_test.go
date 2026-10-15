package tui

import (
	"encoding/json"
	"strings"
	"testing"

	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

func TestConverseUnprocessedEvidenceStaysInHistoryOutsideGraph(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.graph = types.Context{
		Nodes: []types.Node{{ID: "note:earlier", Table: "note", Content: "Earlier graph fact"}},
		Edges: []types.Edge{{ID: "references:earlier", Table: "references"}},
	}
	ctx := &types.Context{
		Nodes: []types.Node{{ID: "note:organized", Table: "note", Content: "Organized graph fact"}},
		Edges: []types.Edge{},
		Unprocessed: []types.UnprocessedChunk{{
			ID: "intake_chunk:pending", IntakeID: "intake-1", ChunkIndex: 0,
			TotalChunks: 1, Content: "Do not show this source in the graph", Unprocessed: true,
		}},
	}

	updated, _ := m.Update(converseResponseMsg{
		response: &types.ConverseResponse{Response: "Pending evidence is available.", Context: ctx},
		userMsg:  "What did I submit?",
	})
	model := updated.(Model)

	if len(model.history) != 1 || model.history[0].Assistant.Context == nil {
		t.Fatal("expected response context in conversation history")
	}
	if len(model.history[0].Assistant.Context.Unprocessed) != 1 || model.context == nil || len(model.context.Unprocessed) != 1 {
		t.Fatal("lost unprocessed evidence from history or context")
	}
	if len(model.graph.Nodes) != 2 || len(model.graph.Edges) != 1 || len(model.graph.Unprocessed) != 0 {
		t.Fatalf("intake evidence changed graph arrays: %+v", model.graph)
	}
	if len(model.graphPanel.nodes) != 2 || len(model.graphPanel.edges) != 1 {
		t.Fatal("intake evidence changed graph panel records")
	}
	rendered, _ := model.graphPanel.renderContent()
	if strings.Contains(rendered, "intake_chunk:pending") || strings.Contains(rendered, ctx.Unprocessed[0].Content) {
		t.Fatal("graph panel rendered unprocessed intake evidence")
	}
}

func TestConverseStreamUnprocessedOnlyContextPreservesExistingGraph(t *testing.T) {
	m := NewModel("http://localhost:8000")
	m.graph = types.Context{
		Nodes: []types.Node{{ID: "note:earlier", Table: "note", Content: "Earlier graph fact"}},
		Edges: []types.Edge{},
	}
	canceled := false

	updated, _ := m.Update(converseStreamEventMsg{
		event: api.SSEEvent{
			Event: "done",
			Data:  json.RawMessage(`{"response":"Your source remains unprocessed.","context":{"nodes":[],"edges":[],"unprocessed":[{"id":"intake_chunk:pending","intake_id":"intake-1","chunk_index":0,"total_chunks":1,"content":"Pending passage","unprocessed":true}]}}`),
		},
		cancel:  func() { canceled = true },
		userMsg: "What did I submit?",
	})
	model := updated.(Model)

	if !canceled {
		t.Error("expected completed stream cancellation")
	}
	if len(model.graph.Nodes) != 1 || model.graph.Nodes[0].ID != "note:earlier" || len(model.graph.Edges) != 0 || len(model.graph.Unprocessed) != 0 {
		t.Fatalf("unprocessed-only response changed graph: %+v", model.graph)
	}
	if model.context == nil || len(model.context.Unprocessed) != 1 || len(model.context.Nodes) != 0 || len(model.context.Edges) != 0 {
		t.Fatalf("lost separate unprocessed context: %+v", model.context)
	}
	if len(model.graphPanel.nodes) != 1 || model.graphPanel.nodes[0].ID != "note:earlier" {
		t.Fatal("unprocessed-only response changed graph panel")
	}
}

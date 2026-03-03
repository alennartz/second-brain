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
						Edges: []types.Edge{{ID: "relates_to:1", Table: "relates_to", Out: "entity:1", In: "entity:2"}},
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

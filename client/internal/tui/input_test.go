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
		{"tell me about @Productivity and", "", false},
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
	if len(suggestions) != 3 {
		t.Errorf("expected 3 suggestions (GTD, Agile, Getting...), got %d", len(suggestions))
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

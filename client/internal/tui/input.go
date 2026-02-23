package tui

import (
	"strings"

	"github.com/charmbracelet/bubbles/textarea"

	"second-brain-client/internal/types"
)

type inputBar struct {
	textArea    textarea.Model
	suggestions []suggestion
	showSuggest bool
}

type suggestion struct {
	label string
	node  types.Node
}

func newInputBar() inputBar {
	ta := textarea.New()
	ta.Placeholder = "Type a message..."
	ta.Focus()
	ta.ShowLineNumbers = false
	ta.SetHeight(3)
	ta.CharLimit = 0
	return inputBar{textArea: ta}
}

func extractAtQuery(input string) (string, bool) {
	idx := strings.LastIndex(input, "@")
	if idx == -1 {
		return "", false
	}
	after := input[idx+1:]
	if strings.Contains(after, " ") {
		return "", false
	}
	return after, true
}

func filterSuggestions(nodes []types.Node, query string) []suggestion {
	query = strings.ToLower(query)
	var results []suggestion
	for _, n := range nodes {
		label := types.NodeLabel(n)
		if query == "" || strings.Contains(strings.ToLower(label), query) {
			results = append(results, suggestion{label: label, node: n})
		}
	}
	return results
}

func resolveAtReferences(text string, nodes []types.Node) (string, []string) {
	var ids []string
	result := text
	for _, n := range nodes {
		label := types.NodeLabel(n)
		ref := "@" + label
		if strings.Contains(result, ref) {
			result = strings.ReplaceAll(result, ref, label)
			ids = append(ids, n.ID)
		}
	}
	return result, ids
}

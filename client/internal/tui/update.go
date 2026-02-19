package tui

import (
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"second-brain-client/internal/types"
)

// submitInput reads the current input value, handles slash commands, and
// dispatches converse requests. Returns the updated model and an optional
// tea.Cmd for async work.
func (m Model) submitInput() (Model, tea.Cmd) {
	value := strings.TrimSpace(m.input.textInput.Value())
	if value == "" {
		return m, nil
	}

	m.input.textInput.SetValue("")
	m.input.showSuggest = false

	switch value {
	case "/quit":
		return m, tea.Quit

	case "/clear":
		m.history = []types.Exchange{}
		m.graph = types.Context{}
		m.context = nil
		m.chat = newChatPanel(m.chat.width, m.chat.height)
		m.graphPanel.setContext(types.Context{})
		m.err = nil
		return m, nil

	case "/graph":
		m.focus = focusGraph
		return m, nil

	default:
		// Resolve @ references
		resolved, hintIDs := resolveAtReferences(value, m.graph.Nodes)
		// TODO: pass hintIDs to the /converse request when the server supports hints
		_ = hintIDs

		// Add user message to chat panel
		m.chat.addMessage("user", value)
		m.loading = true
		m.chat.loading = true
		m.chat.viewport.SetContent(m.chat.renderMessages())

		return m, m.sendConverse(resolved)
	}
}

// sendConverse returns a tea.Cmd that calls the API asynchronously.
func (m Model) sendConverse(message string) tea.Cmd {
	client := m.client
	history := make([]types.Exchange, len(m.history))
	copy(history, m.history)

	return func() tea.Msg {
		resp, err := client.Converse(message, history)
		if err != nil {
			return converseResponseMsg{err: err, userMsg: message}
		}
		return converseResponseMsg{response: resp, userMsg: message}
	}
}

// sendGraphExpand returns a tea.Cmd that fetches a node's connections.
func (m Model) sendGraphExpand(nodeID string) tea.Cmd {
	client := m.client

	return func() tea.Msg {
		resp, err := client.Graph(nodeID)
		if err != nil {
			return graphResponseMsg{err: err}
		}
		return graphResponseMsg{response: resp}
	}
}

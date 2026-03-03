package tui

import (
	"context"
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

// submitInput reads the current input value, handles slash commands, and
// dispatches converse requests. Returns the updated model and an optional
// tea.Cmd for async work.
func (m Model) submitInput() (Model, tea.Cmd) {
	value := strings.TrimSpace(m.input.textArea.Value())
	if value == "" {
		return m, nil
	}

	m.input.textArea.SetValue("")
	m.input.textArea.SetHeight(3)
	m.input.showSuggest = false

	switch value {
	case "/exit":
		return m, tea.Quit

	case "/clear":
		if m.cancelStream != nil {
			m.cancelStream()
			m.cancelStream = nil
		}
		m.history = []types.Exchange{}
		m.graph = types.Context{}
		m.context = nil
		m.chat = newChatPanel(m.chat.width, m.chat.height)
		m.graphPanel.setContext(types.Context{})
		m.err = nil
		m.statusText = ""
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

		return m, m.sendConverseStream(resolved)
	}
}

// sendConverseStream opens an SSE stream and returns a Cmd that delivers
// the first event (or error) as a message.
func (m Model) sendConverseStream(message string) tea.Cmd {
	client := m.client
	history := make([]types.Exchange, len(m.history))
	copy(history, m.history)

	return func() tea.Msg {
		ctx, cancel := context.WithCancel(context.Background())
		events, errc := client.ConverseStream(ctx, message, history)

		return waitForStreamEvent(events, errc, cancel, message)
	}
}

// waitForNextEvent returns a Cmd that reads the next event from the stream.
func waitForNextEvent(events <-chan api.SSEEvent, errc <-chan error, cancel context.CancelFunc, userMsg string) tea.Cmd {
	return func() tea.Msg {
		return waitForStreamEvent(events, errc, cancel, userMsg)
	}
}

// waitForStreamEvent blocks until the next SSE event or error arrives.
func waitForStreamEvent(events <-chan api.SSEEvent, errc <-chan error, cancel context.CancelFunc, userMsg string) tea.Msg {
	for {
		select {
		case evt, ok := <-events:
			if !ok {
				// Channel closed — check for trailing error
				if err, eok := <-errc; eok && err != nil {
					return converseStreamErrMsg{err: err, userMsg: userMsg}
				}
				// Stream ended without done event — treat as error
				return converseStreamErrMsg{
					err:     fmt.Errorf("stream ended unexpectedly"),
					userMsg: userMsg,
				}
			}
			return converseStreamEventMsg{
				event:   evt,
				events:  events,
				errc:    errc,
				cancel:  cancel,
				userMsg: userMsg,
			}
		case err, ok := <-errc:
			if ok && err != nil {
				return converseStreamErrMsg{err: err, userMsg: userMsg}
			}
			// Error channel closed without error, keep reading events
		}
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

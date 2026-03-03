package tui

import (
	"context"
	"encoding/json"
	"fmt"

	tea "github.com/charmbracelet/bubbletea"

	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

const (
	focusChat  = 0
	focusGraph = 1
	maxHistory = 10
)

// chatMessage represents a single message displayed in the chat panel.
type chatMessage struct {
	role string
	text string
}

// Model is the top-level Bubble Tea model for the TUI.
type Model struct {
	client       *api.Client
	history      []types.Exchange
	context      *types.Context
	graph        types.Context
	focus        int
	loading      bool
	err          error
	width        int
	height       int
	chat         chatPanel
	graphPanel   graphPanel
	input        inputBar
	statusText   string
	cancelStream context.CancelFunc
}

// NewModel creates a new TUI model connected to the given server URL.
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

// initPanels sets up the chat, graph, and input sub-components.
func (m *Model) initPanels() {
	m.chat = newChatPanel(40, 10)
	m.graphPanel = newGraphPanel(30, 10)
	m.input = newInputBar()
}

// Init implements tea.Model. Returns the textarea blink command.
func (m Model) Init() tea.Cmd {
	return m.input.textArea.Cursor.BlinkCmd()
}

// Update implements tea.Model. Handles all message types for state transitions.
func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		// Set textarea width immediately so it wraps correctly from the start
		if msg.Width > 4 {
			m.input.textArea.SetWidth(msg.Width - 2)
		}
		return m, nil

	case tea.MouseMsg:
		// Forward mouse events to chat viewport for scroll support
		var cmd tea.Cmd
		m.chat.viewport, cmd = m.chat.viewport.Update(msg)
		return m, cmd

	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyCtrlC:
			if m.cancelStream != nil {
				m.cancelStream()
				m.cancelStream = nil
			}
			return m, tea.Quit

		case tea.KeyTab:
			if m.focus == focusChat {
				m.focus = focusGraph
				m.input.textArea.Blur()
			} else {
				m.focus = focusChat
				m.input.textArea.Focus()
			}
			return m, nil

		case tea.KeyEnter:
			if m.focus == focusChat {
				if msg.Alt {
					// Alt+Enter: insert newline in textarea
					m.input.textArea.InsertString("\n")
					return m, nil
				}
				updated, cmd := m.submitInput()
				return updated, cmd
			}
			// Graph mode: expand selected node
			if m.focus == focusGraph {
				node := m.graphPanel.selectedNode()
				if node != nil {
					return m, m.sendGraphExpand(node.ID)
				}
			}
			return m, nil

		case tea.KeyPgUp:
			if m.focus == focusChat {
				var cmd tea.Cmd
				m.chat.viewport, cmd = m.chat.viewport.Update(msg)
				return m, cmd
			}

		case tea.KeyPgDown:
			if m.focus == focusChat {
				var cmd tea.Cmd
				m.chat.viewport, cmd = m.chat.viewport.Update(msg)
				return m, cmd
			}

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
				m.input.textArea.Focus()
				return m, nil
			}
		}

		// Forward to textarea when chat focused
		if m.focus == focusChat {
			var cmd tea.Cmd
			m.input.textArea, cmd = m.input.textArea.Update(msg)

			// Update autocomplete suggestions
			if query, found := extractAtQuery(m.input.textArea.Value()); found {
				m.input.suggestions = filterSuggestions(m.graph.Nodes, query)
				m.input.showSuggest = len(m.input.suggestions) > 0
			} else {
				m.input.showSuggest = false
			}

			return m, cmd
		}

		return m, nil

	case converseStreamEventMsg:
		m.cancelStream = msg.cancel
		switch msg.event.Event {
		case "status":
			var status struct{ Message string }
			if err := json.Unmarshal(msg.event.Data, &status); err == nil {
				m.statusText = status.Message
				m.chat.loadingText = status.Message
				m.chat.viewport.SetContent(m.chat.renderMessages())
				m.chat.viewport.GotoBottom()
			}
			return m, waitForNextEvent(msg.events, msg.errc, msg.cancel, msg.userMsg)

		case "done":
			var resp types.ConverseResponse
			if err := json.Unmarshal(msg.event.Data, &resp); err != nil {
				m.loading = false
				m.chat.loading = false
				m.statusText = ""
				m.chat.loadingText = ""
				m.cancelStream = nil
				m.err = err
				m.chat.addMessage("brain", "Error: "+err.Error())
				return m, nil
			}
			m.cancelStream = nil
			return m.handleConverseResponse(&resp, msg.userMsg), nil

		case "error":
			var errData struct{ Message string }
			if err := json.Unmarshal(msg.event.Data, &errData); err == nil {
				m.err = fmt.Errorf("%s", errData.Message)
			}
			m.loading = false
			m.chat.loading = false
			m.statusText = ""
			m.chat.loadingText = ""
			m.cancelStream = nil
			if m.err != nil {
				m.chat.addMessage("brain", "Error: "+m.err.Error())
			}
			return m, nil
		}
		// Unknown event type — keep reading
		return m, waitForNextEvent(msg.events, msg.errc, msg.cancel, msg.userMsg)

	case converseStreamErrMsg:
		m.loading = false
		m.chat.loading = false
		m.statusText = ""
		m.chat.loadingText = ""
		m.cancelStream = nil
		m.err = msg.err
		m.chat.addMessage("brain", "Error: "+msg.err.Error())
		return m, nil

	case converseResponseMsg:
		m.loading = false
		m.chat.loading = false
		if msg.err != nil {
			m.err = msg.err
			m.chat.addMessage("brain", "Error: "+msg.err.Error())
			return m, nil
		}
		if msg.response != nil {
			return m.handleConverseResponse(msg.response, msg.userMsg), nil
		}
		return m, nil

	case graphResponseMsg:
		if msg.err != nil {
			m.err = msg.err
			return m, nil
		}
		if msg.response != nil {
			// Merge the node and its connections into the graph
			if !containsNode(m.graph.Nodes, msg.response.Node.ID) {
				m.graph.Nodes = append(m.graph.Nodes, msg.response.Node)
			}
			for _, conn := range msg.response.Connections {
				if !containsNode(m.graph.Nodes, conn.Node.ID) {
					m.graph.Nodes = append(m.graph.Nodes, conn.Node)
				}
				if !containsEdge(m.graph.Edges, conn.Edge.ID) {
					m.graph.Edges = append(m.graph.Edges, conn.Edge)
				}
			}
			// Update graph panel
			m.graphPanel.setContext(m.graph)
		}
		return m, nil

	case clearMsg:
		m.history = []types.Exchange{}
		m.graph = types.Context{}
		m.context = nil
		m.chat = newChatPanel(m.chat.width, m.chat.height)
		m.graphPanel.setContext(types.Context{})
		m.err = nil
		m.statusText = ""
		m.chat.loadingText = ""
		return m, nil

	case errorMsg:
		m.err = msg.err
		return m, nil
	}

	return m, nil
}

// handleConverseResponse processes a successful converse response, updating
// history, context, graph, and chat panel.
func (m Model) handleConverseResponse(resp *types.ConverseResponse, userMsg string) Model {
	m.loading = false
	m.chat.loading = false
	m.statusText = ""
	m.chat.loadingText = ""

	exchange := types.Exchange{
		User: userMsg,
		Assistant: types.AssistantResponse{
			Response: resp.Response,
			Context:  resp.Context,
		},
	}
	m.history = append(m.history, exchange)
	if len(m.history) > maxHistory {
		m.history = m.history[len(m.history)-maxHistory:]
	}

	m.context = resp.Context
	if resp.Context != nil {
		m.graph = *resp.Context
	}

	m.chat.addMessage("brain", resp.Response)
	m.graphPanel.setContext(m.graph)

	return m
}

// View implements tea.Model. Returns the full rendered TUI view.
func (m Model) View() string {
	return m.renderView()
}

// containsNode checks whether a node with the given ID exists in the slice.
func containsNode(nodes []types.Node, id string) bool {
	for _, n := range nodes {
		if n.ID == id {
			return true
		}
	}
	return false
}

// containsEdge checks whether an edge with the given ID exists in the slice.
func containsEdge(edges []types.Edge, id string) bool {
	for _, e := range edges {
		if e.ID == id {
			return true
		}
	}
	return false
}

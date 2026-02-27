package tui

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
)

var (
	headerStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("5")).
			Padding(0, 1)

	panelBorder = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("8"))

	activeBorder = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("5"))

	statusStyle = lipgloss.NewStyle().
			Faint(true).
			Padding(0, 1)
)

// renderView builds the full TUI layout: header, two side-by-side panels,
// input bar, and status line.
func (m Model) renderView() string {
	if m.width == 0 || m.height == 0 {
		return "Initializing..."
	}

	// Header
	header := headerStyle.Render("second-brain")

	// Panel dimensions: subtract header (1), input (3), status (1), borders (2 top/bottom per panel)
	// border takes 2 lines (top+bottom) and 2 columns (left+right) per panel
	panelHeight := m.height - 1 - 3 - 1 - 2 // header + input + status + border vertical
	if panelHeight < 1 {
		panelHeight = 1
	}

	chatWidth := m.width * 60 / 100
	graphWidth := m.width - chatWidth

	// Inner dimensions (subtract border chars)
	chatInner := chatWidth - 2
	graphInner := graphWidth - 2
	if chatInner < 1 {
		chatInner = 1
	}
	if graphInner < 1 {
		graphInner = 1
	}

	// Resize panels
	m.chat.setSize(chatInner, panelHeight)
	m.graphPanel.setSize(graphInner, panelHeight)

	// Render panel contents
	chatContent := m.chat.View()
	graphContent := m.graphPanel.View()

	// Apply borders based on focus
	var chatBox, graphBox string
	if m.focus == focusChat {
		chatBox = activeBorder.Width(chatInner).Height(panelHeight).Render(chatContent)
		graphBox = panelBorder.Width(graphInner).Height(panelHeight).Render(graphContent)
	} else {
		chatBox = panelBorder.Width(chatInner).Height(panelHeight).Render(chatContent)
		graphBox = activeBorder.Width(graphInner).Height(panelHeight).Render(graphContent)
	}

	// Side-by-side panels
	panels := lipgloss.JoinHorizontal(lipgloss.Top, chatBox, graphBox)

	// Input bar
	m.input.textArea.SetWidth(m.width - 2)
	inputView := m.input.textArea.View()

	// Status line
	nodeCount := len(m.graphPanel.nodes)
	edgeCount := len(m.graphPanel.edges)
	var statusText string
	if m.err != nil {
		statusText = fmt.Sprintf("Error: %s | Tab: switch panel | /exit: exit", m.err)
	} else if m.loading {
		statusText = fmt.Sprintf("Thinking... | Nodes: %d | Edges: %d", nodeCount, edgeCount)
	} else {
		statusText = fmt.Sprintf("Enter: send | Alt+Enter: newline | Tab: switch panel | PgUp/PgDn: scroll | /exit | /clear | Nodes: %d | Edges: %d", nodeCount, edgeCount)
	}
	status := statusStyle.Render(statusText)

	return lipgloss.JoinVertical(lipgloss.Left, header, panels, inputView, status)
}

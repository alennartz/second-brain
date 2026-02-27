package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"

	"second-brain-client/internal/types"
)

var (
	nodeEntityStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("3"))
	nodeNoteStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("4"))
	edgeStyle       = lipgloss.NewStyle().Faint(true)
	selectedStyle   = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("2"))
)

type graphPanel struct {
	nodes    []types.Node
	edges    []types.Edge
	cursor   int
	viewport viewport.Model
	width    int
	height   int
}

func newGraphPanel(width, height int) graphPanel {
	vp := viewport.New(width, height)
	g := graphPanel{viewport: vp, width: width, height: height}
	g.refreshViewport()
	return g
}

func (g *graphPanel) setContext(ctx types.Context) {
	g.nodes = ctx.Nodes
	g.edges = ctx.Edges
	g.cursor = 0
	g.refreshViewport()
}

func (g *graphPanel) setSize(width, height int) {
	g.width = width
	g.height = height
	g.viewport.Width = width
	g.viewport.Height = height
	g.refreshViewport()
}

func (g *graphPanel) moveDown() {
	if g.cursor < len(g.nodes)-1 {
		g.cursor++
		g.refreshViewport()
	}
}

func (g *graphPanel) moveUp() {
	if g.cursor > 0 {
		g.cursor--
		g.refreshViewport()
	}
}

func (g *graphPanel) selectedNode() *types.Node {
	if len(g.nodes) == 0 {
		return nil
	}
	return &g.nodes[g.cursor]
}

// refreshViewport re-renders content into the viewport and scrolls to keep the
// cursor visible.
func (g *graphPanel) refreshViewport() {
	content, cursorLine := g.renderContent()
	g.viewport.SetContent(content)

	// Ensure the cursor line is within the visible area.
	top := g.viewport.YOffset
	bottom := top + g.viewport.Height - 1
	if cursorLine < top {
		g.viewport.SetYOffset(cursorLine)
	} else if cursorLine > bottom {
		g.viewport.SetYOffset(cursorLine - g.viewport.Height + 1)
	}
}

// renderContent builds the full text content and returns it along with the line
// number where the cursor node starts (used for scroll-to-cursor).
func (g graphPanel) renderContent() (string, int) {
	if len(g.nodes) == 0 {
		return lipgloss.NewStyle().Faint(true).Render("No graph context"), 0
	}
	wrapStyle := lipgloss.NewStyle().Width(g.width)
	var b strings.Builder
	b.WriteString("Nodes:\n")
	lineCount := 1 // "Nodes:\n" occupies line 0
	cursorLine := 0
	for i, n := range g.nodes {
		if i == g.cursor {
			cursorLine = lineCount
		}
		prefix := "  "
		if i == g.cursor {
			prefix = "> "
		}
		label := types.NodeLabel(n)
		tag := fmt.Sprintf("[%s]", n.Table)
		var line string
		if i == g.cursor {
			line = selectedStyle.Render(fmt.Sprintf("%s%s %s", prefix, tag, label))
		} else {
			style := nodeNoteStyle
			if n.Table == "entity" {
				style = nodeEntityStyle
			}
			line = fmt.Sprintf("%s%s %s", prefix, style.Render(tag), label)
		}
		rendered := wrapStyle.Render(line) + "\n"
		b.WriteString(rendered)
		lineCount += strings.Count(rendered, "\n")
	}
	if len(g.edges) > 0 {
		b.WriteString("\nEdges:\n")
		for _, e := range g.edges {
			fromLabel := g.findNodeLabel(e.From)
			toLabel := g.findNodeLabel(e.To)
			line := edgeStyle.Render(fmt.Sprintf("  %s --%s--> %s", fromLabel, e.Table, toLabel))
			b.WriteString(wrapStyle.Render(line) + "\n")
		}
	}
	return b.String(), cursorLine
}

func (g graphPanel) View() string {
	return g.viewport.View()
}

func (g graphPanel) findNodeLabel(id string) string {
	for _, n := range g.nodes {
		if n.ID == id {
			return types.NodeLabel(n)
		}
	}
	return id
}

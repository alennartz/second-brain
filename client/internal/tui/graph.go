package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"

	"second-brain-client/internal/types"
)

var (
	nodeEntityStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("3"))
	nodeNoteStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("4"))
	edgeTableStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("6"))
	selectedStyle   = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("2"))
	detailStyle     = lipgloss.NewStyle().Faint(true).PaddingLeft(4)
)

type graphPanel struct {
	nodes  []types.Node
	edges  []types.Edge
	cursor int
	width  int
	height int
}

func newGraphPanel(width, height int) graphPanel {
	return graphPanel{width: width, height: height}
}

func (g *graphPanel) setContext(ctx types.Context) {
	g.nodes = ctx.Nodes
	g.edges = ctx.Edges
	g.cursor = 0
}

func (g *graphPanel) setSize(width, height int) {
	g.width = width
	g.height = height
}

func (g *graphPanel) moveDown() {
	if g.cursor < len(g.nodes)-1 {
		g.cursor++
	}
}

func (g *graphPanel) moveUp() {
	if g.cursor > 0 {
		g.cursor--
	}
}

func (g *graphPanel) selectedNode() *types.Node {
	if len(g.nodes) == 0 {
		return nil
	}
	return &g.nodes[g.cursor]
}

func (g graphPanel) View() string {
	if len(g.nodes) == 0 {
		return lipgloss.NewStyle().Faint(true).Render("No graph context")
	}
	wrapStyle := lipgloss.NewStyle().Width(g.width)
	detailWrap := detailStyle.Width(g.width - 4)
	var b strings.Builder
	b.WriteString("Nodes:\n")
	for i, n := range g.nodes {
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
		b.WriteString(wrapStyle.Render(line) + "\n")

		// Show details for the selected node
		if i == g.cursor {
			if n.Description != "" {
				b.WriteString(detailWrap.Render(n.Description) + "\n")
			} else if n.Content != "" && len([]rune(n.Content)) > 60 {
				// Show full content if it was truncated in the label
				b.WriteString(detailWrap.Render(n.Content) + "\n")
			}
			if n.Type != "" {
				b.WriteString(detailWrap.Render("type: "+n.Type) + "\n")
			}
		}
	}
	if len(g.edges) > 0 {
		b.WriteString("\nEdges:\n")
		for _, e := range g.edges {
			fromLabel := truncate(g.findNodeLabel(e.Out), 20)
			toLabel := truncate(g.findNodeLabel(e.In), 20)
			rel := formatEdgeTable(e.Table)
			line := fmt.Sprintf("  %s %s %s",
				fromLabel,
				edgeTableStyle.Render(rel),
				toLabel,
			)
			b.WriteString(wrapStyle.Render(line) + "\n")
			if e.Context != "" {
				b.WriteString(detailWrap.Render(e.Context) + "\n")
			}
		}
	}
	return b.String()
}

// formatEdgeTable converts an edge table name to a readable relation label.
func formatEdgeTable(table string) string {
	switch table {
	case "references":
		return "—references→"
	case "relates_to":
		return "—relates to→"
	case "derived_from":
		return "—derived from→"
	default:
		return "—" + strings.ReplaceAll(table, "_", " ") + "→"
	}
}

// truncate shortens a string to maxLen runes, adding "..." if truncated.
func truncate(s string, maxLen int) string {
	runes := []rune(s)
	if len(runes) <= maxLen {
		return s
	}
	return string(runes[:maxLen-3]) + "..."
}

func (g graphPanel) findNodeLabel(id string) string {
	for _, n := range g.nodes {
		if n.ID == id {
			return types.NodeLabel(n)
		}
	}
	return id
}

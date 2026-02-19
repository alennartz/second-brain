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
	edgeStyle       = lipgloss.NewStyle().Faint(true)
	selectedStyle   = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("2"))
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
	var b strings.Builder
	b.WriteString("Nodes:\n")
	for i, n := range g.nodes {
		prefix := "  "
		if i == g.cursor {
			prefix = "> "
		}
		label := nodeLabel(n)
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
		b.WriteString(line + "\n")
	}
	if len(g.edges) > 0 {
		b.WriteString("\nEdges:\n")
		for _, e := range g.edges {
			fromLabel := g.findNodeLabel(e.From)
			toLabel := g.findNodeLabel(e.To)
			line := edgeStyle.Render(fmt.Sprintf("  %s --%s--> %s", fromLabel, e.Table, toLabel))
			b.WriteString(line + "\n")
		}
	}
	return b.String()
}

func nodeLabel(n types.Node) string {
	if n.Name != "" {
		return n.Name
	}
	if n.Content != "" {
		if len(n.Content) > 60 {
			return n.Content[:57] + "..."
		}
		return n.Content
	}
	return n.ID
}

func (g graphPanel) findNodeLabel(id string) string {
	for _, n := range g.nodes {
		if n.ID == id {
			return nodeLabel(n)
		}
	}
	return id
}

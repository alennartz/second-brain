package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"
)

var (
	userStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("6")).Bold(true)
	brainStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("5")).Bold(true)
)

type chatPanel struct {
	messages []chatMessage
	viewport viewport.Model
	loading  bool
	width    int
	height   int
}

func newChatPanel(width, height int) chatPanel {
	vp := viewport.New(width, height)
	return chatPanel{
		messages: []chatMessage{},
		viewport: vp,
		width:    width,
		height:   height,
	}
}

func (c *chatPanel) addMessage(role, text string) {
	c.messages = append(c.messages, chatMessage{role: role, text: text})
	c.viewport.SetContent(c.renderMessages())
	c.viewport.GotoBottom()
}

func (c *chatPanel) setSize(width, height int) {
	c.width = width
	c.height = height
	c.viewport.Width = width
	c.viewport.Height = height
	c.viewport.SetContent(c.renderMessages())
}

func (c chatPanel) renderMessages() string {
	if len(c.messages) == 0 {
		return lipgloss.NewStyle().Faint(true).Render("Type a message to start...")
	}
	var b strings.Builder
	for _, msg := range c.messages {
		var label string
		if msg.role == "user" {
			label = userStyle.Render("You: ")
		} else {
			label = brainStyle.Render("Brain: ")
		}
		b.WriteString(fmt.Sprintf("\n%s%s\n", label, msg.text))
	}
	if c.loading {
		b.WriteString(fmt.Sprintf("\n%s\n", brainStyle.Render("Thinking...")))
	}
	return b.String()
}

func (c chatPanel) View() string {
	return c.viewport.View()
}

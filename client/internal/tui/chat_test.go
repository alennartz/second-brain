package tui

import (
	"strings"
	"testing"
)

func TestRenderChatEmpty(t *testing.T) {
	c := newChatPanel(40, 10)
	view := c.View()
	if view == "" {
		t.Error("expected non-empty view for empty chat")
	}
}

func TestRenderChatWithMessages(t *testing.T) {
	c := newChatPanel(40, 10)
	c.addMessage("user", "Hello brain")
	c.addMessage("brain", "Hello human")
	view := c.View()
	if !strings.Contains(view, "Hello brain") {
		t.Error("expected user message in view")
	}
	if !strings.Contains(view, "Hello human") {
		t.Error("expected brain message in view")
	}
}

func TestRenderChatLoading(t *testing.T) {
	c := newChatPanel(40, 10)
	c.loading = true
	view := c.View()
	if view == "" {
		t.Error("expected non-empty view when loading")
	}
}

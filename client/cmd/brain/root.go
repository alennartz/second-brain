package main

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/spf13/cobra"

	"second-brain-client/internal/tui"
)

var serverURL string

func newRootCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "brain",
		Short: "Second Brain TUI client",
		Long:  "A terminal client for the Second Brain knowledge engine.",
		RunE: func(cmd *cobra.Command, args []string) error {
			m := tui.NewModel(serverURL)
			p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
			if _, err := p.Run(); err != nil {
				return fmt.Errorf("TUI error: %w", err)
			}
			return nil
		},
	}
	cmd.PersistentFlags().StringVar(&serverURL, "server", envOrDefault("BRAIN_SERVER_URL", "http://localhost:8000"), "server URL")
	cmd.AddCommand(newIngestCmd())
	cmd.AddCommand(newRecallCmd())
	cmd.AddCommand(newGraphCmd())
	return cmd
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

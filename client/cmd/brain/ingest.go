package main

import (
	"fmt"
	"strings"

	"github.com/spf13/cobra"
	"second-brain-client/internal/api"
)

func newIngestCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "ingest [text]",
		Short: "Ingest a thought or piece of knowledge",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			text := strings.Join(args, " ")
			c := api.New(serverURL)
			resp, err := c.Ingest(text, nil)
			if err != nil {
				return fmt.Errorf("ingest failed: %w", err)
			}
			fmt.Fprintln(cmd.OutOrStdout(), resp.Summary)
			return nil
		},
	}
}

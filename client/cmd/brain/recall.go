package main

import (
	"fmt"
	"strings"

	"github.com/spf13/cobra"
	"second-brain-client/internal/api"
)

func newRecallCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "recall [question]",
		Short: "Ask the brain a question",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			question := strings.Join(args, " ")
			c := api.New(serverURL)
			resp, err := c.Recall(question, nil)
			if err != nil {
				return fmt.Errorf("recall failed: %w", err)
			}
			out := cmd.OutOrStdout()
			fmt.Fprintln(out, resp.Answer)
			if resp.Context != nil && len(resp.Context.Nodes) > 0 {
				fmt.Fprintf(out, "\n[%d nodes · %d edges]\n", len(resp.Context.Nodes), len(resp.Context.Edges))
			}
			return nil
		},
	}
}

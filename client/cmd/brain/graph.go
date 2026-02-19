package main

import (
	"fmt"

	"github.com/spf13/cobra"
	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

func newGraphCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "graph [id]",
		Short: "Show a node and its connections",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c := api.New(serverURL)
			resp, err := c.Graph(args[0])
			if err != nil {
				return fmt.Errorf("graph failed: %w", err)
			}
			out := cmd.OutOrStdout()
			fmt.Fprintf(out, "[%s] %s — %s\n", resp.Node.Table, resp.Node.ID, types.NodeLabel(resp.Node))
			if len(resp.Connections) == 0 {
				fmt.Fprintln(out, "  (no connections)")
				return nil
			}
			for _, conn := range resp.Connections {
				fmt.Fprintf(out, "  ──%s──> [%s] %s\n", conn.Edge.Table, conn.Node.Table, types.NodeLabel(conn.Node))
			}
			return nil
		},
	}
}

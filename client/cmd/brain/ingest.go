package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"second-brain-client/internal/api"
)

func newIngestCmd() *cobra.Command {
	var timeout time.Duration
	cmd := &cobra.Command{
		Use:   "ingest [text]",
		Short: "Ingest a thought or piece of knowledge",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			text := strings.Join(args, " ")
			c := api.New(serverURL)

			resp, err := c.IngestWithTimeout(text, nil, timeout)
			if err != nil {
				return fmt.Errorf("ingest failed: %w", err)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Queued %d chunks for background ingestion.\n", resp.ChunksStored)
			return nil
		},
	}
	cmd.Flags().DurationVar(&timeout, "timeout", 5*time.Minute,
		"overall timeout for synchronous staging (e.g. 30s, 2m)")
	return cmd
}

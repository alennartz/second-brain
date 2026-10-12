package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"second-brain-client/internal/api"
)

func newIngestCmd() *cobra.Command {
	var (
		wait    bool
		timeout time.Duration
	)
	cmd := &cobra.Command{
		Use:   "ingest [text]",
		Short: "Ingest a thought or piece of knowledge",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			text := strings.Join(args, " ")
			c := api.New(serverURL)

			if !wait {
				job, err := c.SubmitIngest(text, nil)
				if err != nil {
					return fmt.Errorf("ingest submit failed: %w", err)
				}
				_, _ = fmt.Fprintf(cmd.OutOrStdout(),
					"Submitted ingest job %s (status: %s). Poll %s/ingest/jobs/%s for the result.\n",
					job.JobID, job.Status, serverURL, job.JobID)
				return nil
			}

			resp, err := c.IngestWithTimeout(text, nil, timeout)
			if err != nil {
				return fmt.Errorf("ingest failed: %w", err)
			}
			_, _ = fmt.Fprintln(cmd.OutOrStdout(), resp.Summary)
			return nil
		},
	}
	cmd.Flags().BoolVarP(&wait, "wait", "w", false,
		"block until the ingest job completes and print its summary")
	cmd.Flags().DurationVar(&timeout, "timeout", 5*time.Minute,
		"overall timeout for --wait (e.g. 30s, 2m)")
	return cmd
}

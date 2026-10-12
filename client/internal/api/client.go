package api

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"second-brain-client/internal/types"
)

// SSEEvent represents a single Server-Sent Event.
type SSEEvent struct {
	Event string
	Data  json.RawMessage
}

const (
	// ingestTimeout is the default bound for a full blocking ingest flow.
	ingestTimeout = 5 * time.Minute
	// submitTimeout bounds the fire-and-forget submit POST.
	submitTimeout = 30 * time.Second
	// Poll interval backoff for job status checks.
	pollInitialInterval = 250 * time.Millisecond
	pollMaxInterval     = 2 * time.Second
)

// Client is an HTTP client for the second-brain API server.
type Client struct {
	baseURL      string
	httpClient   *http.Client
	streamClient *http.Client
}

// New creates a new API client targeting the given base URL.
func New(baseURL string) *Client {
	return &Client{
		baseURL:      baseURL,
		httpClient:   &http.Client{Timeout: 30 * time.Second},
		streamClient: &http.Client{}, // no timeout for streaming
	}
}

// Ingest sends text to the server and blocks until the result is ready.
// It handles both server shapes: synchronous (200 + summary) and job-based
// (202 + job_id, then poll GET /ingest/jobs/{id} until completion).
func (c *Client) Ingest(text string, hints []string) (*types.IngestResponse, error) {
	return c.IngestWithTimeout(text, hints, ingestTimeout)
}

// IngestWithTimeout is Ingest bounded by an explicit overall timeout.
func (c *Client) IngestWithTimeout(text string, hints []string, timeout time.Duration) (*types.IngestResponse, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	job, err := c.submitIngest(ctx, text, hints)
	if err != nil {
		return nil, err
	}
	if job.Status == types.JobComplete {
		summary := ""
		if job.Summary != nil {
			summary = *job.Summary
		}
		return &types.IngestResponse{Summary: summary}, nil
	}
	return c.awaitIngestJob(ctx, job.JobID)
}

// SubmitIngest sends text to the server and returns the job state without
// waiting for completion. A synchronous 200 response is returned as an
// already-complete job.
func (c *Client) SubmitIngest(text string, hints []string) (*types.IngestJobResponse, error) {
	ctx, cancel := context.WithTimeout(context.Background(), submitTimeout)
	defer cancel()
	return c.submitIngest(ctx, text, hints)
}

// submitIngest performs the POST and interprets the initial response.
func (c *Client) submitIngest(ctx context.Context, text string, hints []string) (*types.IngestJobResponse, error) {
	req := types.IngestRequest{Text: text, Hints: hints}

	data, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("encode request: %w", err)
	}

	url := fmt.Sprintf("%s/ingest", c.baseURL)
	httpReq, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(data))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq = httpReq.WithContext(ctx)

	httpResp, err := c.streamClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = httpResp.Body.Close() }()

	switch httpResp.StatusCode {
	case http.StatusOK:
		var resp types.IngestResponse
		if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
			return nil, fmt.Errorf("decode response: %w", err)
		}
		return &types.IngestJobResponse{Status: types.JobComplete, Summary: &resp.Summary}, nil
	case http.StatusAccepted:
		var job types.IngestJobResponse
		if err := json.NewDecoder(httpResp.Body).Decode(&job); err != nil {
			return nil, fmt.Errorf("decode job response: %w", err)
		}
		return &job, nil
	default:
		body, _ := io.ReadAll(httpResp.Body)
		return nil, fmt.Errorf("server returned %d: %s", httpResp.StatusCode, body)
	}
}

// awaitIngestJob polls GET /ingest/jobs/{id} until the job completes, fails,
// or ctx expires. Poll interval grows from pollInitialInterval to pollMaxInterval.
func (c *Client) awaitIngestJob(ctx context.Context, jobID string) (*types.IngestResponse, error) {
	interval := pollInitialInterval
	for {
		job, err := c.getIngestJob(jobID)
		if err != nil {
			return nil, err
		}
		switch job.Status {
		case types.JobComplete:
			summary := ""
			if job.Summary != nil {
				summary = *job.Summary
			}
			return &types.IngestResponse{Summary: summary}, nil
		case types.JobFailed:
			msg := "unknown error"
			if job.Error != nil {
				msg = *job.Error
			}
			return nil, fmt.Errorf("ingest job %s failed: %s", jobID, msg)
		}

		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("ingest job %s timed out (status %s): %w", jobID, job.Status, ctx.Err())
		case <-time.After(interval):
			interval *= 2
			if interval > pollMaxInterval {
				interval = pollMaxInterval
			}
		}
	}
}

// getIngestJob fetches the current state of an ingest job.
func (c *Client) getIngestJob(jobID string) (*types.IngestJobResponse, error) {
	url := fmt.Sprintf("%s/ingest/jobs/%s", c.baseURL, url.PathEscape(jobID))
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	httpResp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = httpResp.Body.Close() }()
	if httpResp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(httpResp.Body)
		return nil, fmt.Errorf("server returned %d: %s", httpResp.StatusCode, body)
	}
	var job types.IngestJobResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&job); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &job, nil
}

// Recall asks the server a question and returns a synthesized answer with context.
func (c *Client) Recall(question string, hints []string) (*types.RecallResponse, error) {
	req := types.RecallRequest{Question: question, Hints: hints}
	var resp types.RecallResponse
	if err := c.post("/recall", req, &resp, 0); err != nil {
		return nil, err
	}
	return &resp, nil
}

// Converse sends a conversational message with optional history.
// Uses a longer timeout because the converse endpoint involves nested LLM calls.
func (c *Client) Converse(message string, history []types.Exchange) (*types.ConverseResponse, error) {
	if history == nil {
		history = []types.Exchange{}
	}
	req := types.ConverseRequest{Message: message, History: history}
	var resp types.ConverseResponse
	if err := c.post("/converse", req, &resp, 5*time.Minute); err != nil {
		return nil, err
	}
	return &resp, nil
}

// ConverseStream opens an SSE stream to /converse/stream and returns channels
// for events and errors. The caller's context controls cancellation.
func (c *Client) ConverseStream(ctx context.Context, message string, history []types.Exchange) (<-chan SSEEvent, <-chan error) {
	events := make(chan SSEEvent, 16)
	errc := make(chan error, 1)

	if history == nil {
		history = []types.Exchange{}
	}

	go func() {
		defer close(events)
		defer close(errc)

		body := types.ConverseRequest{Message: message, History: history}
		data, err := json.Marshal(body)
		if err != nil {
			errc <- fmt.Errorf("encode request: %w", err)
			return
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodPost,
			fmt.Sprintf("%s/converse/stream", c.baseURL), bytes.NewReader(data))
		if err != nil {
			errc <- fmt.Errorf("create request: %w", err)
			return
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "text/event-stream")

		resp, err := c.streamClient.Do(req)
		if err != nil {
			errc <- fmt.Errorf("request failed: %w", err)
			return
		}
		defer func() { _ = resp.Body.Close() }()

		if resp.StatusCode != http.StatusOK {
			respBody, _ := io.ReadAll(resp.Body)
			errc <- fmt.Errorf("server returned %d: %s", resp.StatusCode, respBody)
			return
		}

		parseSSE(ctx, resp.Body, events, errc)
	}()

	return events, errc
}

// parseSSE reads an SSE stream from r and emits events on the channel.
func parseSSE(ctx context.Context, r io.Reader, events chan<- SSEEvent, errc chan<- error) {
	scanner := bufio.NewScanner(r)
	var eventType string
	var dataBuf strings.Builder

	for scanner.Scan() {
		if ctx.Err() != nil {
			return
		}

		line := scanner.Text()

		if line == "" {
			// Blank line = dispatch event
			if dataBuf.Len() > 0 {
				evt := SSEEvent{
					Event: eventType,
					Data:  json.RawMessage(dataBuf.String()),
				}
				if evt.Event == "" {
					evt.Event = "message"
				}
				select {
				case events <- evt:
				case <-ctx.Done():
					return
				}
			}
			eventType = ""
			dataBuf.Reset()
			continue
		}

		if strings.HasPrefix(line, "event:") {
			eventType = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		} else if strings.HasPrefix(line, "data:") {
			if dataBuf.Len() > 0 {
				dataBuf.WriteByte('\n')
			}
			dataBuf.WriteString(strings.TrimSpace(strings.TrimPrefix(line, "data:")))
		}
		// Ignore comment lines (starting with ':') and unknown fields
	}

	if err := scanner.Err(); err != nil && ctx.Err() == nil {
		errc <- fmt.Errorf("read SSE stream: %w", err)
	}
}

// Graph fetches a node and its connections from the knowledge graph.
func (c *Client) Graph(id string) (*types.GraphResponse, error) {
	url := fmt.Sprintf("%s/graph/%s", c.baseURL, url.PathEscape(id))
	httpResp, err := c.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = httpResp.Body.Close() }()
	if httpResp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(httpResp.Body)
		return nil, fmt.Errorf("server returned %d: %s", httpResp.StatusCode, body)
	}
	var resp types.GraphResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
		return nil, fmt.Errorf("decode response: %w", err)
	}
	return &resp, nil
}

// post is a helper that JSON-encodes reqBody, POSTs to the given path,
// checks for a 200 status, and JSON-decodes the response into respBody.
// When timeout is non-zero it overrides the client's default timeout for
// that single request (used for slow endpoints like /converse).
func (c *Client) post(path string, reqBody any, respBody any, timeout time.Duration) error {
	data, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("encode request: %w", err)
	}
	url := fmt.Sprintf("%s%s", c.baseURL, path)

	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// Choose the appropriate HTTP client. When the caller requests a timeout
	// longer than the httpClient's default (30s), use streamClient (no
	// built-in timeout) so the context deadline actually governs.
	client := c.httpClient
	if timeout > 0 {
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		defer cancel()
		req = req.WithContext(ctx)
		if timeout > c.httpClient.Timeout {
			client = c.streamClient
		}
	}

	httpResp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer func() { _ = httpResp.Body.Close() }()
	if httpResp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(httpResp.Body)
		return fmt.Errorf("server returned %d: %s", httpResp.StatusCode, body)
	}
	if err := json.NewDecoder(httpResp.Body).Decode(respBody); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	return nil
}

package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"second-brain-client/internal/types"
)

// Client is an HTTP client for the second-brain API server.
type Client struct {
	baseURL    string
	httpClient *http.Client
}

// New creates a new API client targeting the given base URL.
func New(baseURL string) *Client {
	return &Client{
		baseURL:    baseURL,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// Ingest sends text to the server for ingestion into the knowledge graph.
func (c *Client) Ingest(text string, hints []string) (*types.IngestResponse, error) {
	req := types.IngestRequest{Text: text, Hints: hints}
	var resp types.IngestResponse
	if err := c.post("/ingest", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// Recall asks the server a question and returns a synthesized answer with context.
func (c *Client) Recall(question string, hints []string) (*types.RecallResponse, error) {
	req := types.RecallRequest{Question: question, Hints: hints}
	var resp types.RecallResponse
	if err := c.post("/recall", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// Converse sends a conversational message with optional history.
func (c *Client) Converse(message string, history []types.Exchange) (*types.ConverseResponse, error) {
	if history == nil {
		history = []types.Exchange{}
	}
	req := types.ConverseRequest{Message: message, History: history}
	var resp types.ConverseResponse
	if err := c.post("/converse", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// Graph fetches a node and its connections from the knowledge graph.
func (c *Client) Graph(id string) (*types.GraphResponse, error) {
	url := fmt.Sprintf("%s/graph/%s", c.baseURL, id)
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
func (c *Client) post(path string, reqBody any, respBody any) error {
	data, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("encode request: %w", err)
	}
	url := fmt.Sprintf("%s%s", c.baseURL, path)
	httpResp, err := c.httpClient.Post(url, "application/json", bytes.NewReader(data))
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

package api_test

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

func TestIngest(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/ingest" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		body, _ := io.ReadAll(r.Body)
		var req types.IngestRequest
		_ = json.Unmarshal(body, &req)
		if req.Text != "test thought" {
			t.Errorf("got text %q", req.Text)
		}
		_ = json.NewEncoder(w).Encode(types.IngestResponse{Summary: "Stored 1 note."})
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	resp, err := c.Ingest("test thought", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Summary != "Stored 1 note." {
		t.Errorf("got summary %q", resp.Summary)
	}
}

func TestRecall(t *testing.T) {
	ctx := &types.Context{
		Nodes: []types.Node{{ID: "note:1", Table: "note", Content: "GTD stuff"}},
		Edges: []types.Edge{},
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/recall" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		_ = json.NewEncoder(w).Encode(types.RecallResponse{Answer: "You know about GTD.", Context: ctx})
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	resp, err := c.Recall("what do I know?", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Answer != "You know about GTD." {
		t.Errorf("got answer %q", resp.Answer)
	}
	if resp.Context == nil || len(resp.Context.Nodes) != 1 {
		t.Error("expected 1 node in context")
	}
}

func TestConverse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/converse" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		body, _ := io.ReadAll(r.Body)
		var req types.ConverseRequest
		_ = json.Unmarshal(body, &req)
		if req.Message != "hello" {
			t.Errorf("got message %q", req.Message)
		}
		_ = json.NewEncoder(w).Encode(types.ConverseResponse{Response: "Hi there."})
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	resp, err := c.Converse("hello", nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Response != "Hi there." {
		t.Errorf("got response %q", resp.Response)
	}
}

func TestGraph(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/graph/note:abc" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		_ = json.NewEncoder(w).Encode(types.GraphResponse{
			Node:        types.Node{ID: "note:abc", Table: "note", Content: "test"},
			Connections: []types.Connection{},
		})
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	resp, err := c.Graph("note:abc")
	if err != nil {
		t.Fatal(err)
	}
	if resp.Node.ID != "note:abc" {
		t.Errorf("got node ID %q", resp.Node.ID)
	}
}

func TestServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("internal error"))
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	_, err := c.Recall("test", nil)
	if err == nil {
		t.Error("expected error for 500 response")
	}
}

func TestServerUnreachable(t *testing.T) {
	c := api.New("http://localhost:1") // nothing listening
	_, err := c.Recall("test", nil)
	if err == nil {
		t.Error("expected error for unreachable server")
	}
}

func TestConverseStream(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/converse/stream" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}

		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.WriteHeader(http.StatusOK)

		events := []string{
			"event: status\ndata: {\"message\":\"Searching knowledge base...\"}\n\n",
			"event: status\ndata: {\"message\":\"Running hybrid search...\"}\n\n",
			"event: done\ndata: {\"response\":\"the answer\",\"context\":null}\n\n",
		}
		for _, e := range events {
			_, _ = fmt.Fprint(w, e)
			if f, ok := w.(http.Flusher); ok {
				f.Flush()
			}
		}
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	events, errc := c.ConverseStream(context.Background(), "hello", nil)

	var got []api.SSEEvent
	for e := range events {
		got = append(got, e)
	}
	if err, ok := <-errc; ok && err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(got) != 3 {
		t.Fatalf("expected 3 events, got %d", len(got))
	}

	if got[0].Event != "status" {
		t.Errorf("event[0].Event = %q, want %q", got[0].Event, "status")
	}
	var status struct{ Message string }
	if err := json.Unmarshal(got[0].Data, &status); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if status.Message != "Searching knowledge base..." {
		t.Errorf("event[0] message = %q", status.Message)
	}

	if got[2].Event != "done" {
		t.Errorf("event[2].Event = %q, want %q", got[2].Event, "done")
	}
	var done struct{ Response string }
	if err := json.Unmarshal(got[2].Data, &done); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if done.Response != "the answer" {
		t.Errorf("event[2] response = %q", done.Response)
	}
}

func TestConverseStream_ServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("internal error"))
	}))
	defer srv.Close()

	c := api.New(srv.URL)
	events, errc := c.ConverseStream(context.Background(), "hello", nil)

	// Drain events (should be empty)
	for range events {
	}

	err, ok := <-errc
	if !ok || err == nil {
		t.Error("expected error for 500 response")
	}
}

func TestConverseStream_Cancel(t *testing.T) {
	started := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprint(w, "event: status\ndata: {\"message\":\"working...\"}\n\n")
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
		close(started)
		// Block until client disconnects
		<-w.(http.CloseNotifier).CloseNotify() //nolint:staticcheck
	}))
	defer srv.Close()

	ctx, cancel := context.WithCancel(context.Background())
	c := api.New(srv.URL)
	events, errc := c.ConverseStream(ctx, "hello", nil)

	// Wait for at least one event
	<-started
	e, ok := <-events
	if !ok {
		t.Fatal("expected at least one event before cancel")
	}
	if e.Event != "status" {
		t.Errorf("event = %q, want status", e.Event)
	}

	cancel()

	// Drain remaining
	for range events {
	}
	for range errc {
	}
}

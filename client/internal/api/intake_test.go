package api_test

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

func TestIngestReturnsStoredChunkCountWithoutPolling(t *testing.T) {
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.Method != http.MethodPost || r.URL.Path != "/ingest" {
			t.Errorf("unexpected job polling request: %s %s", r.Method, r.URL.Path)
			http.Error(w, "job polling removed", http.StatusNotFound)
			return
		}
		var request types.IngestRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Errorf("decode request: %v", err)
		}
		if request.Text != "Original source text" || len(request.Hints) != 1 || request.Hints[0] != "entity:topic" {
			t.Errorf("unexpected intake request: %+v", request)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"chunks_stored":7}`)
	}))
	defer srv.Close()

	response, err := api.New(srv.URL).Ingest("Original source text", []string{"entity:topic"})
	if err != nil {
		t.Fatal(err)
	}
	if response.ChunksStored != 7 {
		t.Errorf("got %d stored chunks, want 7", response.ChunksStored)
	}
	if requests.Load() != 1 {
		t.Errorf("got %d requests, want one synchronous POST", requests.Load())
	}
}

func TestRecallRetainsUnprocessedContextApartFromGraph(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/recall" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{
			"answer":"This source is not organized yet.",
			"context":{
				"nodes":[{"id":"note:organized","table":"note"}],
				"edges":[],
				"unprocessed":[{"id":"intake_chunk:pending","intake_id":"intake-1","chunk_index":0,"total_chunks":1,"content":"Pending source","source":"cli","unprocessed":true}]
			}
		}`)
	}))
	defer srv.Close()

	response, err := api.New(srv.URL).Recall("What did I submit?", nil)
	if err != nil {
		t.Fatal(err)
	}
	if response.Context == nil {
		t.Fatal("expected recall context")
	}
	if len(response.Context.Nodes) != 1 || response.Context.Nodes[0].ID != "note:organized" || len(response.Context.Edges) != 0 {
		t.Fatalf("intake evidence changed graph arrays: %+v", response.Context)
	}
	if len(response.Context.Unprocessed) != 1 || response.Context.Unprocessed[0].ID != "intake_chunk:pending" {
		t.Fatalf("lost intake evidence: %+v", response.Context.Unprocessed)
	}
}

func TestConverseStreamRetainsUnprocessedOnlyDoneContext(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/converse/stream" {
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "event: done\ndata: "+`{"response":"Pending source evidence.","context":{"nodes":[],"edges":[],"unprocessed":[{"id":"intake_chunk:pending","intake_id":"intake-1","chunk_index":0,"total_chunks":1,"content":"Source evidence","unprocessed":true}]}}`+"\n\n")
	}))
	defer srv.Close()

	events, errors := api.New(srv.URL).ConverseStream(context.Background(), "What did I submit?", nil)
	doneCount := 0
	for event := range events {
		if event.Event != "done" {
			t.Errorf("unexpected event %q", event.Event)
			continue
		}
		doneCount++
		var response types.ConverseResponse
		if err := json.Unmarshal(event.Data, &response); err != nil {
			t.Fatal(err)
		}
		if response.Context == nil || len(response.Context.Unprocessed) != 1 {
			t.Fatalf("lost unprocessed-only context: %+v", response.Context)
		}
		if len(response.Context.Nodes) != 0 || len(response.Context.Edges) != 0 {
			t.Fatal("unprocessed evidence entered graph arrays")
		}
	}
	for err := range errors {
		if err != nil {
			t.Fatal(err)
		}
	}
	if doneCount != 1 {
		t.Errorf("got %d done events, want 1", doneCount)
	}
}

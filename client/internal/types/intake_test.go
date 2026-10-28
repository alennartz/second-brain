package types_test

import (
	"encoding/json"
	"reflect"
	"testing"

	"second-brain-client/internal/types"
)

func TestIngestResponseDecodesStoredChunkCount(t *testing.T) {
	var response types.IngestResponse
	if err := json.Unmarshal([]byte(`{"chunks_stored":7}`), &response); err != nil {
		t.Fatal(err)
	}
	if response.ChunksStored != 7 {
		t.Fatalf("got %d stored chunks, want 7", response.ChunksStored)
	}
}

func TestCaptureAndFreshnessFieldsDecodeFromResponses(t *testing.T) {
	raw := `{
		"answer":"Recent evidence.",
		"context":{
			"nodes":[{"id":"note:recent","table":"note","freshness_at":"2026-01-02T03:04:05+02:00"}],
			"edges":[{"id":"references:recent","table":"references","in":"entity:topic","out":"note:recent","freshness_at":"2026-01-02T03:04:05+02:00"}],
			"unprocessed":[{"id":"intake_chunk:recent","intake_id":"intake-1","chunk_index":0,"total_chunks":1,"content":"Recent source","captured_at":"2026-01-02T03:04:05+02:00","unprocessed":true}]
		}
	}`
	var response types.RecallResponse
	if err := json.Unmarshal([]byte(raw), &response); err != nil {
		t.Fatal(err)
	}
	if response.Context == nil {
		t.Fatal("expected context")
	}
	if got := response.Context.Nodes[0].FreshnessAt; got != "2026-01-02T03:04:05+02:00" {
		t.Fatalf("got node freshness_at %q", got)
	}
	if got := response.Context.Edges[0].FreshnessAt; got != "2026-01-02T03:04:05+02:00" {
		t.Fatalf("got edge freshness_at %q", got)
	}
	if got := response.Context.Unprocessed[0].CapturedAt; got != "2026-01-02T03:04:05+02:00" {
		t.Fatalf("got chunk captured_at %q", got)
	}
}

func TestRecallContextKeepsUnprocessedEvidenceOutsideGraphArrays(t *testing.T) {
	raw := `{
		"answer":"The intake contains a pending fact.",
		"context":{
			"nodes":[{"id":"note:organized","table":"note","content":"Organized fact"}],
			"edges":[{"id":"references:organized","table":"references","in":"entity:topic","out":"note:organized"}],
			"unprocessed":[{
				"id":"intake_chunk:pending","table":"intake_chunk","intake_id":"intake-1",
				"chunk_index":1,"total_chunks":3,"content":"Pending source passage",
				"source":"cli","hints":["entity:topic"],"unprocessed":true
			}]
		}
	}`
	var response types.RecallResponse
	if err := json.Unmarshal([]byte(raw), &response); err != nil {
		t.Fatal(err)
	}
	if response.Context == nil {
		t.Fatal("expected context")
	}
	ctx := response.Context
	if len(ctx.Nodes) != 1 || ctx.Nodes[0].ID != "note:organized" {
		t.Fatalf("intake evidence changed graph nodes: %+v", ctx.Nodes)
	}
	if len(ctx.Edges) != 1 || ctx.Edges[0].ID != "references:organized" {
		t.Fatalf("intake evidence changed graph edges: %+v", ctx.Edges)
	}
	want := []types.UnprocessedChunk{{
		ID: "intake_chunk:pending", Table: "intake_chunk", IntakeID: "intake-1",
		ChunkIndex: 1, TotalChunks: 3, Content: "Pending source passage",
		Source: "cli", Hints: []string{"entity:topic"}, Unprocessed: true,
	}}
	if !reflect.DeepEqual(ctx.Unprocessed, want) {
		t.Fatalf("got unprocessed evidence %+v, want %+v", ctx.Unprocessed, want)
	}

	encoded, err := json.Marshal(response)
	if err != nil {
		t.Fatal(err)
	}
	var roundTrip types.RecallResponse
	if err := json.Unmarshal(encoded, &roundTrip); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(roundTrip, response) {
		t.Fatalf("context changed during JSON round trip: %+v", roundTrip)
	}
}

func TestConverseHistoryRetainsUnprocessedOnlyContext(t *testing.T) {
	raw := `{
		"message":"Tell me more.",
		"history":[{
			"user":"What did I submit?",
			"assistant":{
				"response":"Your source is still unprocessed.",
				"context":{
					"nodes":[],"edges":[],
					"unprocessed":[{"id":"intake_chunk:pending","intake_id":"intake-1","chunk_index":0,"total_chunks":1,"content":"Source passage","unprocessed":true}]
				}
			}
		}]
	}`
	var request types.ConverseRequest
	if err := json.Unmarshal([]byte(raw), &request); err != nil {
		t.Fatal(err)
	}
	if len(request.History) != 1 || request.History[0].Assistant.Context == nil {
		t.Fatal("expected history with context")
	}
	ctx := request.History[0].Assistant.Context
	if len(ctx.Nodes) != 0 || len(ctx.Edges) != 0 {
		t.Fatal("unprocessed evidence entered graph arrays")
	}
	if len(ctx.Unprocessed) != 1 || ctx.Unprocessed[0].ID != "intake_chunk:pending" {
		t.Fatalf("lost unprocessed history: %+v", ctx.Unprocessed)
	}
	encoded, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	var roundTrip types.ConverseRequest
	if err := json.Unmarshal(encoded, &roundTrip); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(roundTrip, request) {
		t.Fatal("history context changed during JSON round trip")
	}
}

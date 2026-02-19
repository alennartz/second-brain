package api_test

import (
	"encoding/json"
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

package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"second-brain-client/internal/types"
)

func TestIngestCommand(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(types.IngestResponse{Summary: "Stored 1 note."})
	}))
	defer srv.Close()

	var buf bytes.Buffer
	cmd := newRootCmd()
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"ingest", "--server", srv.URL, "my test thought"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("Stored 1 note.")) {
		t.Errorf("output: %s", buf.String())
	}
}

func TestRecallCommand(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(types.RecallResponse{
			Answer:  "You know about GTD.",
			Context: &types.Context{Nodes: []types.Node{{ID: "note:1", Table: "note", Content: "GTD"}}, Edges: []types.Edge{}},
		})
	}))
	defer srv.Close()

	var buf bytes.Buffer
	cmd := newRootCmd()
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"recall", "--server", srv.URL, "what do I know?"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("You know about GTD.")) {
		t.Errorf("output: %s", buf.String())
	}
}

func TestGraphCommand(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(types.GraphResponse{
			Node:        types.Node{ID: "note:abc", Table: "note", Content: "test content"},
			Connections: []types.Connection{},
		})
	}))
	defer srv.Close()

	var buf bytes.Buffer
	cmd := newRootCmd()
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"graph", "--server", srv.URL, "note:abc"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("note:abc")) {
		t.Errorf("output: %s", buf.String())
	}
}

func TestRootNoArgsLaunchesTUI(t *testing.T) {
	cmd := newRootCmd()
	cmd.SetArgs([]string{"--help"})
	if err := cmd.Execute(); err != nil {
		t.Fatal(err)
	}
}

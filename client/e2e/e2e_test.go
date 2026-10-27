//go:build e2e

package e2e_test

import (
	"fmt"
	"net/http"
	"os"
	"testing"
	"time"

	"second-brain-client/internal/api"
)

var serverURL string

func TestMain(m *testing.M) {
	serverURL = os.Getenv("E2E_SERVER_URL")
	if serverURL == "" {
		serverURL = "http://localhost:8001"
	}

	// Wait for server to be healthy
	client := &http.Client{Timeout: 2 * time.Second}
	healthURL := fmt.Sprintf("%s/health", serverURL)
	for i := range 30 {
		resp, err := client.Get(healthURL)
		if err == nil && resp.StatusCode == http.StatusOK {
			_ = resp.Body.Close()
			break
		}
		if i == 29 {
			fmt.Fprintf(os.Stderr, "server not healthy after 30 attempts at %s\n", healthURL)
			os.Exit(1)
		}
		time.Sleep(1 * time.Second)
	}

	os.Exit(m.Run())
}

func TestHealth(t *testing.T) {
	resp, err := http.Get(fmt.Sprintf("%s/health", serverURL))
	if err != nil {
		t.Fatalf("health request failed: %v", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
}

func TestIngest(t *testing.T) {
	c := api.New(serverURL)
	resp, err := c.Ingest("The Feynman Technique is a learning method where you explain concepts in simple terms.", nil)
	if err != nil {
		t.Fatalf("ingest failed: %v", err)
	}
	if resp.ChunksStored <= 0 {
		t.Errorf("expected stored chunks, got %d", resp.ChunksStored)
	}
}

func TestRecall(t *testing.T) {
	c := api.New(serverURL)

	// Ingest first so there's something to recall
	_, err := c.Ingest("Spaced repetition is an evidence-based learning technique using increasing intervals.", nil)
	if err != nil {
		t.Fatalf("ingest failed: %v", err)
	}

	resp, err := c.Recall("What do I know about learning?", nil)
	if err != nil {
		t.Fatalf("recall failed: %v", err)
	}
	if resp.Answer == "" {
		t.Error("expected non-empty answer")
	}
}

func TestGraphNotFound(t *testing.T) {
	c := api.New(serverURL)
	_, err := c.Graph("note:nonexistent")
	if err == nil {
		t.Error("expected error for nonexistent node")
	}
}

package types

// Node represents a note or entity in the knowledge graph.
type Node struct {
	ID          string `json:"id"`
	Table       string `json:"table"`
	Content     string `json:"content,omitempty"`
	Name        string `json:"name,omitempty"`
	Type        string `json:"type,omitempty"`
	Description string `json:"description,omitempty"`
	Summary     string `json:"summary,omitempty"`
}

// Edge represents a relationship between two nodes.
// SurrealDB RELATE creates edges with "in" (target) and "out" (source) fields.
type Edge struct {
	ID      string `json:"id"`
	Table   string `json:"table"`
	In      string `json:"in"`
	Out     string `json:"out"`
	Context string `json:"context,omitempty"`
}

// Context is the curated subset of nodes/edges the agent deemed relevant.
type Context struct {
	Nodes []Node `json:"nodes"`
	Edges []Edge `json:"edges"`
}

// AssistantResponse is the assistant's part of a conversation exchange.
type AssistantResponse struct {
	Response string   `json:"response"`
	Context  *Context `json:"context,omitempty"`
}

// Exchange is a single user/assistant turn in conversation history.
type Exchange struct {
	User      string            `json:"user"`
	Assistant AssistantResponse `json:"assistant"`
}

// --- Request types ---

// IngestRequest is the payload for POST /ingest.
type IngestRequest struct {
	Text  string   `json:"text"`
	Hints []string `json:"hints,omitempty"`
}

// RecallRequest is the payload for POST /recall.
type RecallRequest struct {
	Question string   `json:"question"`
	Hints    []string `json:"hints,omitempty"`
}

// ConverseRequest is the payload for POST /converse.
type ConverseRequest struct {
	Message string     `json:"message"`
	History []Exchange `json:"history"`
}

// --- Response types ---

// IngestResponse is returned by POST /ingest on servers that answer synchronously.
type IngestResponse struct {
	Summary string `json:"summary"`
}

// JobStatus is the lifecycle state of an async ingest job.
type JobStatus string

const (
	JobPending  JobStatus = "pending"
	JobRunning  JobStatus = "running"
	JobComplete JobStatus = "complete"
	JobFailed   JobStatus = "failed"
)

// IngestJobResponse is returned by POST /ingest (202) and GET /ingest/jobs/{id}.
type IngestJobResponse struct {
	JobID   string    `json:"job_id"`
	Status  JobStatus `json:"status"`
	Summary *string   `json:"summary"`
	Error   *string   `json:"error"`
}

// RecallResponse is returned by POST /recall.
type RecallResponse struct {
	Answer  string   `json:"answer"`
	Context *Context `json:"context,omitempty"`
}

// ConverseResponse is returned by POST /converse.
type ConverseResponse struct {
	Response string   `json:"response"`
	Context  *Context `json:"context,omitempty"`
}

// Connection is a single edge + the node on the other end, returned by /graph/{id}.
type Connection struct {
	Edge Edge `json:"edge"`
	Node Node `json:"node"`
}

// GraphResponse is returned by GET /graph/{id}.
type GraphResponse struct {
	Node        Node         `json:"node"`
	Connections []Connection `json:"connections"`
}

// NodeLabel returns a human-readable label for a node, preferring Name, then
// Content (truncated to 60 chars), and falling back to ID.
func NodeLabel(n Node) string {
	if n.Name != "" {
		return n.Name
	}
	if n.Content != "" {
		runes := []rune(n.Content)
		if len(runes) > 60 {
			return string(runes[:57]) + "..."
		}
		return n.Content
	}
	return n.ID
}

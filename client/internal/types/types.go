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
type Edge struct {
	ID      string `json:"id"`
	Table   string `json:"table"`
	From    string `json:"from"`
	To      string `json:"to"`
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

// IngestResponse is returned by POST /ingest.
type IngestResponse struct {
	Summary string `json:"summary"`
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

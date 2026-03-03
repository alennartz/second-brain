package tui

import (
	"context"

	"second-brain-client/internal/api"
	"second-brain-client/internal/types"
)

type converseResponseMsg struct {
	response *types.ConverseResponse
	userMsg  string
	err      error
}

// converseStreamEventMsg carries an SSE event plus the channels/state
// needed to continue reading the stream.
type converseStreamEventMsg struct {
	event   api.SSEEvent
	events  <-chan api.SSEEvent
	errc    <-chan error
	cancel  context.CancelFunc
	userMsg string
}

// converseStreamErrMsg carries a stream-level error.
type converseStreamErrMsg struct {
	err     error
	userMsg string
}

type graphResponseMsg struct {
	response *types.GraphResponse
	err      error
}

type errorMsg struct {
	err error
}

type clearMsg struct{}

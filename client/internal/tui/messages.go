package tui

import "second-brain-client/internal/types"

type converseResponseMsg struct {
	response *types.ConverseResponse
	userMsg  string
	err      error
}

type graphResponseMsg struct {
	response *types.GraphResponse
	err      error
}

type errorMsg struct {
	err error
}

type clearMsg struct{}

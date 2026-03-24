# Bubble Tea Architecture

> Source: [github.com/charmbracelet/bubbletea](https://github.com/charmbracelet/bubbletea) README
> The Elm Architecture for Go terminal applications

## Overview

Bubble Tea is a Go framework based on [The Elm Architecture](https://guide.elm-lang.org/architecture/) for building terminal UIs. It's well-suited for simple and complex terminal applications, either inline, full-window, or a mix of both.

Features include a high-performance cell-based renderer, built-in color downsampling, declarative views, high-fidelity keyboard and mouse handling, and native clipboard support.

## The Three Core Methods

Bubble Tea programs are comprised of a **model** that describes application state and three methods:

- **`Init()`** — returns an initial command for the application to run
- **`Update(Msg)`** — handles incoming events and updates the model accordingly
- **`View()`** — renders the UI based on the data in the model

### The Model

The model stores application state. It can be any type, but a struct usually makes the most sense.

```go
type model struct {
    choices  []string
    cursor   int
    selected map[int]struct{}
}
```

### Init

Returns an initial `Cmd`. Return `nil` for "no command."

```go
func (m model) Init() tea.Cmd {
    return nil
}
```

### Update

Called when "things happen." Looks at what happened (via a `Msg`) and returns an updated model. Can also return a `Cmd` to trigger more I/O.

Messages come in as `tea.Msg` (an `interface{}`). Use type switches to handle different message types:

```go
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case tea.KeyPressMsg:
        switch msg.String() {
        case "ctrl+c", "q":
            return m, tea.Quit
        case "up", "k":
            if m.cursor > 0 {
                m.cursor--
            }
        case "down", "j":
            if m.cursor < len(m.choices)-1 {
                m.cursor++
            }
        case "enter", "space":
            _, ok := m.selected[m.cursor]
            if ok {
                delete(m.selected, m.cursor)
            } else {
                m.selected[m.cursor] = struct{}{}
            }
        }
    }
    return m, nil
}
```

`tea.Quit` is a special command that tells the runtime to exit.

### View

Renders the entire UI as a string. You never worry about redrawing — Bubble Tea handles diffing and repainting.

```go
func (m model) View() tea.View {
    s := "What should we buy at the market?\n\n"
    for i, choice := range m.choices {
        cursor := " "
        if m.cursor == i {
            cursor = ">"
        }
        checked := " "
        if _, ok := m.selected[i]; ok {
            checked = "x"
        }
        s += fmt.Sprintf("%s [%s] %s\n", cursor, checked, choice)
    }
    s += "\nPress q to quit.\n"
    return tea.NewView(s)
}
```

### Running the Program

```go
func main() {
    p := tea.NewProgram(initialModel())
    if _, err := p.Run(); err != nil {
        fmt.Printf("Error: %v", err)
        os.Exit(1)
    }
}
```

## Commands and I/O

Commands (`tea.Cmd`) are functions that perform I/O and return a `Msg`:

```go
type Cmd func() Msg
```

### Common Command Patterns

```go
// Batch: run commands concurrently
tea.Batch(cmd1, cmd2, cmd3)

// Sequence: run commands in order
tea.Sequence(cmd1, cmd2, cmd3)

// Tick: timer that fires once
tea.Tick(time.Second, func(t time.Time) tea.Msg {
    return tickMsg(t)
})

// Custom command for async work
func fetchData() tea.Cmd {
    return func() tea.Msg {
        resp, err := http.Get("https://example.com")
        if err != nil {
            return errMsg{err}
        }
        defer resp.Body.Close()
        // ... parse response ...
        return dataMsg{data}
    }
}
```

### Custom Messages

Define your own message types for async results:

```go
type dataMsg struct{ data []Item }
type errMsg struct{ err error }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case dataMsg:
        m.items = msg.data
        return m, nil
    case errMsg:
        m.err = msg.err
        return m, nil
    }
    return m, nil
}
```

## Debugging

### With Delve

Since Bubble Tea controls stdin/stdout, run delve in headless mode:

```bash
dlv debug --headless --api-version=2 --listen=127.0.0.1:43000
# Then from another terminal:
dlv connect 127.0.0.1:43000
```

### Logging to File

```go
if len(os.Getenv("DEBUG")) > 0 {
    f, err := tea.LogToFile("debug.log", "debug")
    if err != nil {
        fmt.Println("fatal:", err)
        os.Exit(1)
    }
    defer f.Close()
}
```

Monitor with `tail -f debug.log` in another terminal.

## Companion Libraries

- [Bubbles](https://github.com/charmbracelet/bubbles): Reusable TUI components (text input, viewport, list, etc.)
- [Lip Gloss](https://github.com/charmbracelet/lipgloss): Terminal styling and layout
- [Harmonica](https://github.com/charmbracelet/harmonica): Spring animations
- [BubbleZone](https://github.com/lrstanley/bubblezone): Mouse event tracking for components

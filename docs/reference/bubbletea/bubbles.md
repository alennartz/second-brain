# Bubbles — TUI Components for Bubble Tea

> Source: [github.com/charmbracelet/bubbles](https://github.com/charmbracelet/bubbles)
> Reusable, production-ready components for Bubble Tea applications

## Overview

Bubbles provides pre-built components that follow the Bubble Tea `Model` interface. Each component has its own `Init()`, `Update()`, and `View()` methods, and can be composed into larger applications.

## Components

### Spinner

A loading indicator with several built-in styles.

```go
import "github.com/charmbracelet/bubbles/spinner"

s := spinner.New()
s.Spinner = spinner.Dot  // or Line, MiniDot, Jump, Pulse, Points, Globe, Moon, Monkey
s.Style = lipgloss.NewStyle().Foreground(lipgloss.Color("205"))
```

- [Basic example](https://github.com/charmbracelet/bubbletea/blob/main/examples/spinner/main.go)
- [Multiple spinners](https://github.com/charmbracelet/bubbletea/blob/main/examples/spinners/main.go)

### Text Input

Single-line text input field. Supports unicode, pasting, in-place scrolling.

```go
import "github.com/charmbracelet/bubbles/textinput"

ti := textinput.New()
ti.Placeholder = "Type something..."
ti.Focus()
ti.CharLimit = 156
ti.Width = 20
```

- [Single field](https://github.com/charmbracelet/bubbletea/blob/main/examples/textinput/main.go)
- [Multiple fields](https://github.com/charmbracelet/bubbletea/blob/main/examples/textinputs/main.go)

### Text Area

Multi-line text input. Supports unicode, pasting, vertical scrolling.

```go
import "github.com/charmbracelet/bubbles/textarea"

ta := textarea.New()
ta.Placeholder = "Write your message..."
ta.Focus()
ta.SetWidth(80)
ta.SetHeight(10)
```

Key methods:
- `Value() string` — get the current content
- `SetValue(s string)` — set content
- `Focus()` / `Blur()` — manage focus
- `SetWidth(w int)` / `SetHeight(h int)` — set dimensions
- `InsertString(s string)` — insert text at cursor

- [Chat input example](https://github.com/charmbracelet/bubbletea/blob/main/examples/chat/main.go)
- [Story time example](https://github.com/charmbracelet/bubbletea/blob/main/examples/textarea/main.go)

### Viewport

Vertically scrollable content pane. Supports pager keybindings and mouse wheel.

```go
import "github.com/charmbracelet/bubbles/viewport"

vp := viewport.New(80, 20)  // width, height
vp.SetContent(longString)
```

Key methods:
- `SetContent(s string)` — set the scrollable content
- `GotoTop()` / `GotoBottom()` — scroll to extremes
- `LineDown(n int)` / `LineUp(n int)` — scroll by lines
- `ViewDown() / ViewUp()` — scroll by page
- `AtTop() bool` / `AtBottom() bool` — check scroll position
- `ScrollPercent() float64` — current scroll percentage

- [Pager example](https://github.com/charmbracelet/bubbletea/blob/main/examples/pager/main.go)

### Table

Display and navigate tabular data with columns and rows. Supports vertical scrolling.

```go
import "github.com/charmbracelet/bubbles/table"

columns := []table.Column{
    {Title: "Name", Width: 20},
    {Title: "Age", Width: 5},
}
rows := []table.Row{
    {"Alice", "30"},
    {"Bob", "25"},
}
t := table.New(
    table.WithColumns(columns),
    table.WithRows(rows),
    table.WithFocused(true),
    table.WithHeight(7),
)
```

- [Example](https://github.com/charmbracelet/bubbletea/blob/main/examples/table/main.go)

### List

Batteries-included list browser with pagination, fuzzy filtering, help, spinner, and status messages.

```go
import "github.com/charmbracelet/bubbles/list"

items := []list.Item{
    item{title: "Raspberry Pi", desc: "A tiny computer"},
    item{title: "Arduino", desc: "A microcontroller"},
}
l := list.New(items, list.NewDefaultDelegate(), 0, 0)
l.Title = "My Items"
```

Items must implement:
```go
type Item interface {
    FilterValue() string
}
```

- [Default list](https://github.com/charmbracelet/bubbletea/blob/main/examples/list-default/main.go)
- [Simple list](https://github.com/charmbracelet/bubbletea/blob/main/examples/list-simple/main.go)
- [Fancy list](https://github.com/charmbracelet/bubbletea/blob/main/examples/list-fancy/main.go)

### Progress

Customizable progress bar with optional animation. Supports solid and gradient fills.

```go
import "github.com/charmbracelet/bubbles/progress"

p := progress.New(progress.WithDefaultGradient())
// or
p := progress.New(progress.WithSolidFill("#5A56E0"))

// Render at a percentage (0.0–1.0)
p.ViewAs(0.5)
```

- [Animated](https://github.com/charmbracelet/bubbletea/blob/main/examples/progress-animated/main.go)
- [Static](https://github.com/charmbracelet/bubbletea/blob/main/examples/progress-static/main.go)

### Paginator

Page navigation with dot-style or numeric display.

```go
import "github.com/charmbracelet/bubbles/paginator"

p := paginator.New()
p.Type = paginator.Dots  // or paginator.Arabic
p.PerPage = 10
p.SetTotalPages(len(items))
```

### File Picker

Navigate the filesystem and select files, optionally filtered by extension.

```go
import "github.com/charmbracelet/bubbles/filepicker"

fp := filepicker.New()
fp.AllowedTypes = []string{".md", ".txt"}
fp.CurrentDirectory, _ = os.UserHomeDir()
```

### Timer / Stopwatch

```go
import "github.com/charmbracelet/bubbles/timer"
import "github.com/charmbracelet/bubbles/stopwatch"

t := timer.NewWithInterval(5*time.Minute, time.Second)
sw := stopwatch.NewWithInterval(time.Second)
```

### Help

Auto-generated help view from keybindings. Single and multi-line modes.

```go
import "github.com/charmbracelet/bubbles/help"

h := help.New()
h.View(myKeyMap)  // myKeyMap implements help.KeyMap
```

### Key Bindings

Non-visual keybinding management with help text support.

```go
import "github.com/charmbracelet/bubbles/key"

type keyMap struct {
    Up   key.Binding
    Down key.Binding
    Quit key.Binding
}

var keys = keyMap{
    Up: key.NewBinding(
        key.WithKeys("k", "up"),
        key.WithHelp("↑/k", "move up"),
    ),
    Down: key.NewBinding(
        key.WithKeys("j", "down"),
        key.WithHelp("↓/j", "move down"),
    ),
    Quit: key.NewBinding(
        key.WithKeys("q", "ctrl+c"),
        key.WithHelp("q", "quit"),
    ),
}

// In Update:
case tea.KeyMsg:
    switch {
    case key.Matches(msg, keys.Up):
        // handle up
    case key.Matches(msg, keys.Down):
        // handle down
    }
```

## Composition Pattern

Bubbles are designed to be embedded in your model:

```go
type model struct {
    input    textinput.Model
    viewport viewport.Model
    spinner  spinner.Model
    loading  bool
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    var cmds []tea.Cmd

    // Update sub-components
    var cmd tea.Cmd
    m.input, cmd = m.input.Update(msg)
    cmds = append(cmds, cmd)

    m.viewport, cmd = m.viewport.Update(msg)
    cmds = append(cmds, cmd)

    if m.loading {
        m.spinner, cmd = m.spinner.Update(msg)
        cmds = append(cmds, cmd)
    }

    return m, tea.Batch(cmds...)
}

func (m model) View() string {
    return lipgloss.JoinVertical(lipgloss.Left,
        m.viewport.View(),
        m.input.View(),
    )
}
```

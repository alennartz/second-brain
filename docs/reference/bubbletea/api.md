# Bubble Tea API Reference

> Source: [pkg.go.dev/github.com/charmbracelet/bubbletea](https://pkg.go.dev/github.com/charmbracelet/bubbletea)
> Package `tea` — full type and function reference

## Core Interface

### Model

```go
type Model interface {
    Init() Cmd
    Update(Msg) (Model, Cmd)
    View() string
}
```

The central interface. Implement these three methods to build a Bubble Tea program.

### Msg

```go
type Msg interface{}
```

Messages contain data from I/O operations. They trigger the Update function.

### Cmd

```go
type Cmd func() Msg
```

A command performs I/O and returns a message when complete. `nil` means "no command."

## Program

### NewProgram

```go
func NewProgram(model Model, opts ...ProgramOption) *Program
```

Creates a new Program.

### Program Methods

| Method | Description |
|--------|-------------|
| `Run() (Model, error)` | Runs the event loop, blocks until quit. Returns final model. |
| `Send(msg Msg)` | Injects a message from outside the program |
| `Quit()` | Quit from outside the program |
| `Kill()` | Stop immediately, skip final render |
| `ReleaseTerminal() error` | Restore terminal for external process |
| `RestoreTerminal() error` | Re-acquire terminal after release |
| `Wait()` | Block until program finishes shutting down |
| `Printf(template, args...)` | Print above the TUI (unmanaged output) |
| `Println(args...)` | Print line above the TUI |

### Program Options

```go
tea.NewProgram(model,
    tea.WithAltScreen(),          // full-window mode
    tea.WithMouseCellMotion(),    // mouse click/drag/wheel events
    tea.WithMouseAllMotion(),     // + hover events
    tea.WithFPS(60),              // custom max FPS (default 60, max 120)
    tea.WithInput(reader),        // custom input (nil to disable)
    tea.WithOutput(writer),       // custom output
    tea.WithInputTTY(),           // open new TTY for input
    tea.WithContext(ctx),         // cancellable context
    tea.WithEnvironment(env),     // custom env vars (SSH sessions)
    tea.WithFilter(filterFn),     // pre-process messages
    tea.WithReportFocus(),        // receive FocusMsg/BlurMsg
    tea.WithoutBracketedPaste(),  // disable bracketed paste
    tea.WithoutCatchPanics(),     // don't catch panics
    tea.WithoutRenderer(),        // no TUI rendering (CLI mode)
    tea.WithoutSignalHandler(),   // handle signals yourself
    tea.WithoutSignals(),         // ignore OS signals (testing)
)
```

## Built-in Messages

### Keyboard

```go
type KeyMsg struct {
    Type  KeyType
    Runes []rune
    Alt   bool
}

// Usage in Update:
case tea.KeyMsg:
    switch msg.String() {
    case "enter":     // enter key
    case "ctrl+c":    // ctrl+c
    case "up":        // arrow up
    case "a":         // letter a
    }

// Or by type:
case tea.KeyMsg:
    switch msg.Type {
    case tea.KeyEnter:
    case tea.KeyUp, tea.KeyDown:
    case tea.KeyRunes:
        letter := string(msg.Runes)
    }
```

**Key types:** `KeyEnter`, `KeyBackspace`, `KeyTab`, `KeyEsc`, `KeySpace`, `KeyUp`, `KeyDown`, `KeyLeft`, `KeyRight`, `KeyHome`, `KeyEnd`, `KeyPgUp`, `KeyPgDown`, `KeyDelete`, `KeyInsert`, `KeyF1`–`KeyF20`, `KeyCtrlA`–`KeyCtrlZ`, `KeyShiftTab`, `KeyCtrlUp/Down/Left/Right`, `KeyShiftUp/Down/Left/Right`, `KeyCtrlShiftUp/Down/Left/Right`

### Window

```go
type WindowSizeMsg struct {
    Width  int
    Height int
}
```

Sent on startup and on every terminal resize.

### Mouse

```go
type MouseMsg struct {
    X, Y   int
    Shift  bool
    Alt    bool
    Ctrl   bool
    Action MouseAction  // Press, Release, Motion
    Button MouseButton  // Left, Middle, Right, WheelUp, WheelDown, etc.
}
```

Requires `WithMouseCellMotion()` or `WithMouseAllMotion()`.

### Focus

```go
type FocusMsg struct{}  // terminal gained focus
type BlurMsg struct{}   // terminal lost focus
```

Requires `WithReportFocus()`.

## Built-in Commands

### Quit / Suspend / Interrupt

```go
tea.Quit      // exit the program
tea.Suspend   // suspend (ctrl+z behavior)
tea.Interrupt // interrupt (ctrl+c behavior)
```

### Batch and Sequence

```go
// Run concurrently, no ordering guarantee
tea.Batch(cmd1, cmd2, cmd3)

// Run in order, each waits for the previous
tea.Sequence(cmd1, cmd2, cmd3)
```

### Timers

```go
// Fires once after duration (independent of system clock)
tea.Tick(duration, func(t time.Time) tea.Msg {
    return myTickMsg(t)
})

// Fires in sync with system clock
tea.Every(duration, func(t time.Time) tea.Msg {
    return myTickMsg(t)
})
```

### Screen Management

```go
tea.EnterAltScreen()       // switch to alt screen
tea.ExitAltScreen()        // back to normal screen
tea.ClearScreen()          // clear screen
tea.ShowCursor()           // show cursor
tea.HideCursor()           // hide cursor
tea.SetWindowTitle("App")  // set terminal title
```

### Mouse Control

```go
tea.EnableMouseCellMotion()  // click, release, wheel, drag
tea.EnableMouseAllMotion()   // + hover
tea.DisableMouse()           // disable mouse
```

### Bracketed Paste

```go
tea.EnableBracketedPaste()
tea.DisableBracketedPaste()
```

### Focus Reporting

```go
tea.EnableReportFocus()
tea.DisableReportFocus()
```

### External Process Execution

```go
// Run an external process (e.g., editor), pausing the TUI
tea.ExecProcess(exec.Command("vim", "file.txt"), func(err error) tea.Msg {
    return editorFinishedMsg{err}
})
```

### Window Size Query

```go
tea.WindowSize()  // request current terminal size (sends WindowSizeMsg)
```

### Printing

```go
tea.Printf("template %s", arg)  // print above TUI
tea.Println("message")           // print line above TUI
```

## Errors

```go
tea.ErrInterrupted   // program received SIGINT or InterruptMsg
tea.ErrProgramKilled // program was killed
tea.ErrProgramPanic  // program recovered from a panic
```

## Logging

```go
// Log to file (can't use stdout — TUI is using it)
f, err := tea.LogToFile("debug.log", "debug")
defer f.Close()
```

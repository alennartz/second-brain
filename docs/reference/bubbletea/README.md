# Bubble Tea Reference

> Source: [github.com/charmbracelet/bubbletea](https://github.com/charmbracelet/bubbletea)
> Retrieved: 2026-03-23

Local reference docs for the Bubble Tea TUI framework and its companion libraries.

## Files

| File | Description |
|------|-------------|
| [architecture.md](architecture.md) | Elm Architecture tutorial — Model, Init, Update, View lifecycle |
| [api.md](api.md) | Full API reference — all types, functions, commands, and program options |
| [bubbles.md](bubbles.md) | Bubbles component library — spinner, text input, textarea, viewport, list, table, etc. |
| [lipgloss.md](lipgloss.md) | Lip Gloss styling — colors, borders, padding, layout, tables, trees |

## Quick Orientation

Bubble Tea implements [The Elm Architecture](https://guide.elm-lang.org/architecture/):

```
Init() → Cmd        // initial command (I/O to perform at startup)
Update(Msg) → (Model, Cmd)  // handle events, return updated state + next command
View() → string     // render the entire UI from current state
```

**Messages (`Msg`)** are events — keypresses, window resizes, custom messages from commands.
**Commands (`Cmd`)** are functions that perform I/O and return a `Msg` when done.
**The runtime** manages the event loop: dispatches messages, calls Update, re-renders View.

Key patterns used in the second-brain client:
- `tea.KeyMsg` / `tea.KeyPressMsg` for keyboard input
- `tea.WindowSizeMsg` for terminal resize
- `tea.Batch()` for concurrent commands
- `tea.Sequence()` for ordered commands
- Custom message types for async operation results (API calls, SSE streams)
- `tea.Cmd` returning functions for background work (HTTP requests)

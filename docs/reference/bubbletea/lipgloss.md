# Lip Gloss — Terminal Styling & Layout

> Source: [github.com/charmbracelet/lipgloss](https://github.com/charmbracelet/lipgloss)
> Declarative, CSS-like styling for terminal applications

## Overview

Lip Gloss takes an expressive, declarative approach to terminal rendering. Users familiar with CSS will feel at home.

```go
import "charm.land/lipgloss/v2"

var style = lipgloss.NewStyle().
    Bold(true).
    Foreground(lipgloss.Color("#FAFAFA")).
    Background(lipgloss.Color("#7D56F4")).
    PaddingTop(2).
    PaddingLeft(4).
    Width(22)

lipgloss.Println(style.Render("Hello, kitty"))
```

## Colors

### Color Profiles

```go
// ANSI 16 (4-bit)
lipgloss.Color("5")       // magenta
lipgloss.Color("12")      // light blue

// ANSI 256 (8-bit)
lipgloss.Color("86")      // aqua
lipgloss.Color("201")     // hot pink

// True Color (24-bit)
lipgloss.Color("#0000FF") // blue
lipgloss.Color("#04B575") // green
```

### Named ANSI Constants

`lipgloss.Black`, `Red`, `Green`, `Yellow`, `Blue`, `Magenta`, `Cyan`, `White`, `BrightBlack`, `BrightRed`, `BrightGreen`, `BrightYellow`, `BrightBlue`, `BrightMagenta`, `BrightCyan`, `BrightWhite`

### Adaptive Colors (Light/Dark backgrounds)

```go
hasDarkBG := lipgloss.HasDarkBackground(os.Stdin, os.Stdout)
lightDark := lipgloss.LightDark(hasDarkBG)
myColor := lightDark(lipgloss.Color("#D7FFAE"), lipgloss.Color("#D75FEE"))
```

With Bubble Tea:
```go
func (m model) Init() tea.Cmd {
    return tea.RequestBackgroundColor
}
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case tea.BackgroundColorMsg:
        m.styles = newStyles(msg.IsDark())
    }
    return m, nil
}
```

### Color Utilities

```go
lipgloss.Darken(color, 0.5)
lipgloss.Lighten(color, 0.35)
lipgloss.Complementary(color)
lipgloss.Alpha(color, 0.2)
lipgloss.Blend1D(steps, color1, color2)           // 1D gradient
lipgloss.Blend2D(w, h, angle, c1, c2, c3)         // 2D gradient
```

### Automatic Downsampling

Lip Gloss automatically downsamples colors to the terminal's capabilities. Use `lipgloss.Println`, `lipgloss.Sprint`, etc. for automatic handling. With Bubble Tea, this is built-in.

## Inline Formatting

```go
var style = lipgloss.NewStyle().
    Bold(true).
    Italic(true).
    Faint(true).
    Blink(true).
    Strikethrough(true).
    Underline(true).
    Reverse(true)
```

### Underline Styles

```go
s := lipgloss.NewStyle().
    UnderlineStyle(lipgloss.UnderlineCurly).
    UnderlineColor(lipgloss.Color("#FF0000"))
```

Styles: `UnderlineNone`, `UnderlineSingle`, `UnderlineDouble`, `UnderlineCurly`, `UnderlineDotted`, `UnderlineDashed`

### Hyperlinks

```go
s := lipgloss.NewStyle().
    Hyperlink("https://charm.land")
lipgloss.Println(s.Render("Visit Charm"))
```

## Block-Level Formatting

### Padding & Margins

```go
// Individual sides
lipgloss.NewStyle().PaddingTop(2).PaddingRight(4).PaddingBottom(2).PaddingLeft(4)
lipgloss.NewStyle().MarginTop(2).MarginRight(4).MarginBottom(2).MarginLeft(4)

// CSS-style shorthand
lipgloss.NewStyle().Padding(2)           // all sides
lipgloss.NewStyle().Margin(2, 4)         // vertical, horizontal
lipgloss.NewStyle().Padding(1, 4, 2)     // top, horizontal, bottom
lipgloss.NewStyle().Margin(2, 4, 3, 1)   // top, right, bottom, left

// Custom fill characters
lipgloss.NewStyle().Padding(1, 2).PaddingChar('·')
lipgloss.NewStyle().Margin(1, 2).MarginChar('░')
```

### Text Alignment

```go
lipgloss.NewStyle().Width(24).Align(lipgloss.Left)
lipgloss.NewStyle().Width(24).Align(lipgloss.Right)
lipgloss.NewStyle().Width(24).Align(lipgloss.Center)
```

### Width & Height

```go
lipgloss.NewStyle().Width(24).Height(32)
```

### Borders

```go
// Built-in border styles
lipgloss.NormalBorder()
lipgloss.RoundedBorder()
lipgloss.ThickBorder()
lipgloss.DoubleBorder()
lipgloss.ASCIIBorder()
lipgloss.MarkdownBorder()

// Apply a border
lipgloss.NewStyle().
    BorderStyle(lipgloss.RoundedBorder()).
    BorderForeground(lipgloss.Color("228"))

// Selective sides
lipgloss.NewStyle().
    Border(lipgloss.ThickBorder(), true, false)  // top/bottom only

// Gradient borders
lipgloss.NewStyle().
    Border(lipgloss.RoundedBorder()).
    BorderForegroundBlend(lipgloss.Color("#FF0000"), lipgloss.Color("#0000FF"))

// Custom border
var myBorder = lipgloss.Border{
    Top: "._.:*:", Bottom: "._.:*:",
    Left: "|*", Right: "|*",
    TopLeft: "*", TopRight: "*",
    BottomLeft: "*", BottomRight: "*",
}
```

### Enforcing Rules

```go
style.Inline(true).Render("text")               // force single line
style.Inline(true).MaxWidth(5).Render("text")    // single line, max 5 cells
style.MaxWidth(5).MaxHeight(5).Render("text")    // constrained block
```

## Layout Utilities

### Joining

```go
// Horizontal join (align along bottom edges)
lipgloss.JoinHorizontal(lipgloss.Bottom, blockA, blockB, blockC)

// Vertical join (align along center axes)
lipgloss.JoinVertical(lipgloss.Center, blockA, blockB)

// Custom alignment position (0.0–1.0)
lipgloss.JoinHorizontal(0.2, blockA, blockB)
```

### Measuring

```go
width := lipgloss.Width(renderedBlock)
height := lipgloss.Height(renderedBlock)
w, h := lipgloss.Size(renderedBlock)
```

### Placing in Whitespace

```go
// Center horizontally in 80-cell space
lipgloss.PlaceHorizontal(80, lipgloss.Center, block)

// Place at bottom of 30-cell tall space
lipgloss.PlaceVertical(30, lipgloss.Bottom, block)

// Place in bottom-right of 80x30 space
lipgloss.Place(80, 30, lipgloss.Right, lipgloss.Bottom, block)
```

### Compositing (Layered rendering)

```go
a := lipgloss.NewLayer(content1).X(4).Y(2).Z(1)
b := lipgloss.NewLayer(content2).X(22).Y(1)
output := compositor.Compose(a, b).Render()
```

### Text Wrapping

```go
wrapped := lipgloss.Wrap(styledText, 40, " ")
```

## Style Operations

### Copying

Styles are value types — assignment creates a true copy:

```go
style := lipgloss.NewStyle().Foreground(lipgloss.Color("219"))
copy := style                  // true copy
wild := style.Blink(true)     // new copy with blink
```

### Inheritance

Only unset rules are inherited:

```go
styleA := lipgloss.NewStyle().
    Foreground(lipgloss.Color("229")).
    Background(lipgloss.Color("63"))

// Only background is inherited (foreground already set)
styleB := lipgloss.NewStyle().
    Foreground(lipgloss.Color("201")).
    Inherit(styleA)
```

### Unsetting Rules

```go
style.Bold(true).UnsetBold()
style.Background(lipgloss.Color("227")).UnsetBackground()
```

## Rendering Tables

```go
import "charm.land/lipgloss/v2/table"

rows := [][]string{
    {"Chinese", "您好"},
    {"Japanese", "こんにちは"},
}

t := table.New().
    Border(lipgloss.NormalBorder()).
    BorderStyle(lipgloss.NewStyle().Foreground(lipgloss.Color("99"))).
    StyleFunc(func(row, col int) lipgloss.Style {
        if row == table.HeaderRow {
            return headerStyle
        }
        return cellStyle
    }).
    Headers("LANGUAGE", "GREETING").
    Rows(rows...)

lipgloss.Println(t)
```

## Rendering Lists

```go
import "charm.land/lipgloss/v2/list"

l := list.New("A", "B", "C")
l = l.Enumerator(list.Roman)  // or list.Arabic, list.Alphabet, list.Bullet, list.Tree

// Nested lists
l := list.New(
    "Fruits", list.New("Apple", "Banana"),
    "Veggies", list.New("Carrot", "Pea"),
)
```

## Rendering Trees

```go
import "charm.land/lipgloss/v2/tree"

t := tree.Root(".").
    Child("src").
    Child(tree.New().Root("internal").
        Child("api").
        Child("tui"))

// Enumerators: tree.DefaultEnumerator, tree.RoundedEnumerator
t = t.Enumerator(tree.RoundedEnumerator)
```

## Tab Handling

```go
style := lipgloss.NewStyle()                       // tabs → 4 spaces (default)
style = style.TabWidth(2)                          // tabs → 2 spaces
style = style.TabWidth(0)                          // remove tabs
style = style.TabWidth(lipgloss.NoTabConversion)   // leave tabs as-is
```

package connect

import (
	"fmt"
	"html"
	"strings"
	"unicode/utf8"

	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"github.com/yuin/goldmark"
	"github.com/yuin/goldmark/ast"
	"github.com/yuin/goldmark/extension"
	extast "github.com/yuin/goldmark/extension/ast"
	"github.com/yuin/goldmark/text"
	"github.com/yuin/goldmark/util"
)

func RenderText(response *bridge.ChatResponse) string {
	src := []byte(response.Response)
	doc := goldmark.New(goldmark.WithExtensions(extension.Table)).Parser().Parse(text.NewReader(src))
	var out strings.Builder
	var inline func(ast.Node) string
	inline = func(n ast.Node) string {
		switch v := n.(type) {
		case *ast.Text:
			s := string(v.Segment.Value(src))
			if v.SoftLineBreak() || v.HardLineBreak() {
				s += "\n"
			}
			return html.UnescapeString(string(util.UnescapePunctuations([]byte(s))))
		case *ast.String:
			return string(v.Value)
		case *ast.AutoLink:
			return string(v.URL(src))
		}
		var b strings.Builder
		for ch := n.FirstChild(); ch != nil; ch = ch.NextSibling() {
			b.WriteString(inline(ch))
		}
		if link, ok := n.(*ast.Link); ok {
			url := string(link.Destination)
			if strings.HasPrefix(url, "https://") || strings.HasPrefix(url, "http://") {
				fmt.Fprintf(&b, " (%s)", url)
			}
		}
		return b.String()
	}
	var block func(ast.Node)
	block = func(n ast.Node) {
		switch n.(type) {
		case *extast.Table:
			headers := []string{}
			rowIndex := 0
			for row := n.FirstChild(); row != nil; row = row.NextSibling() {
				cells := []string{}
				for cell := row.FirstChild(); cell != nil; cell = cell.NextSibling() {
					cells = append(cells, inline(cell))
				}
				if rowIndex == 0 {
					headers = cells
				} else {
					for i, v := range cells {
						label := fmt.Sprintf("列 %d", i+1)
						if i < len(headers) {
							label = headers[i]
						}
						fmt.Fprintf(&out, "%s：%s\n", label, v)
					}
					out.WriteByte('\n')
				}
				rowIndex++
			}
			return
		case *ast.FencedCodeBlock, *ast.CodeBlock:
			lines := n.Lines()
			for i := 0; i < lines.Len(); i++ {
				line := lines.At(i)
				out.Write(line.Value(src))
			}
			out.WriteByte('\n')
			return
		case *ast.Paragraph, *ast.Heading, *ast.TextBlock:
			out.WriteString(inline(n))
			out.WriteString("\n\n")
			return
		case *ast.HTMLBlock:
			out.WriteString("[HTML 内容请在工作台查看]\n")
			return
		}
		for ch := n.FirstChild(); ch != nil; ch = ch.NextSibling() {
			block(ch)
		}
	}
	block(doc)
	for _, citation := range response.Citations {
		if strings.HasPrefix(citation.URL, "https://") || strings.HasPrefix(citation.URL, "http://") {
			fmt.Fprintf(&out, "[%d] %s\n%s\n", citation.Index, citation.Title, citation.URL)
		}
	}
	for _, artifact := range response.Artifacts {
		name := artifact.Title
		if name == "" {
			name = artifact.Name
		}
		if name == "" {
			name = "生成产物"
		}
		fmt.Fprintf(&out, "\n产物：%s（请在工作台查看）\n", name)
	}
	return nonempty(strings.TrimSpace(out.String()))
}
func SplitText(value string, limit int) []string {
	if limit < 32 {
		limit = 32
	}
	remaining := strings.TrimSpace(value)
	parts := []string{}
	// Reserve space for numbering; limits are UTF-8 bytes, not a count of Go bytes cut mid-rune.
	size := limit - 24
	for len(remaining) > size {
		end := size
		for !utf8.RuneStart(remaining[end]) {
			end--
		}
		if split := strings.LastIndex(remaining[:end], "\n"); split > end/2 {
			end = split + 1
		}
		parts = append(parts, remaining[:end])
		remaining = remaining[end:]
	}
	if remaining != "" {
		parts = append(parts, remaining)
	}
	if len(parts) > 1 {
		for i := range parts {
			parts[i] = fmt.Sprintf("(%d/%d) %s", i+1, len(parts), parts[i])
		}
	}
	return parts
}

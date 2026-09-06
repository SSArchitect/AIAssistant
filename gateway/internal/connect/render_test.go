package connect

import (
	"github.com/aan/agent-assistant-gateway/internal/bridge"
	"strings"
	"testing"
	"unicode/utf8"
)

func TestTableRenderingPreservesValuesAndEscapes(t *testing.T) {
	result := RenderText(&bridge.ChatResponse{Response: "| 项目 | 费用 |\n|---|---|\n| A\\|B | -12.5% |\n| C | ¥100/月 |\n\n[详情](https://example.com)", Reasoning: "SECRET"})
	for _, want := range []string{"项目：A|B", "费用：-12.5%", "费用：¥100/月", "https://example.com"} {
		if !strings.Contains(result, want) {
			t.Fatalf("missing %q: %s", want, result)
		}
	}
	if strings.Contains(result, "SECRET") || strings.Contains(result, "|---") {
		t.Fatal(result)
	}
}
func TestArtifactNoticeDoesNotExposePrivateURLsOrMetadata(t *testing.T) {
	result := RenderText(&bridge.ChatResponse{Artifacts: []bridge.ChatArtifact{{Name: "report.xlsx", URL: "https://private.invalid/token", Metadata: map[string]any{"private": "secret"}}}})
	if !strings.Contains(result, "report.xlsx") || !strings.Contains(result, "工作台") || strings.Contains(result, "private.invalid") || strings.Contains(result, "secret") {
		t.Fatal(result)
	}
}

func TestSplitTextIsCompleteAndUTF8Safe(t *testing.T) {
	value := strings.Repeat("中文😀行\n", 200)
	parts := SplitText(value, 120)
	var joined strings.Builder
	for _, part := range parts {
		if len(part) > 120 || !utf8.ValidString(part) {
			t.Fatal(part)
		}
		_, body, _ := strings.Cut(part, ") ")
		joined.WriteString(body)
	}
	if joined.String() != strings.TrimSpace(value) {
		t.Fatal("content lost during splitting")
	}
}

package handlers

import (
	"encoding/json"
	"strings"
	"unicode"
)

const documentMaxContentRunes = 220000

func trimDocumentContent(value string) string {
	value = strings.TrimSpace(strings.ReplaceAll(value, "\u0000", ""))
	return limitRunes(value, documentMaxContentRunes)
}

func titleFromDocumentContent(content, fallback string) string {
	for _, line := range strings.Split(content, "\n") {
		line = strings.TrimSpace(strings.TrimLeft(line, "#>-*0123456789. "))
		if line != "" {
			return cleanDocumentTitle(line)
		}
	}
	if cleaned := cleanDocumentTitle(fallback); cleaned != "" {
		return cleaned
	}
	return "Untitled Document"
}

func summarizeDocumentContent(content string) string {
	paragraphs := strings.Split(strings.ReplaceAll(content, "\r\n", "\n"), "\n\n")
	for _, paragraph := range paragraphs {
		cleaned := strings.Join(strings.Fields(paragraph), " ")
		if cleaned != "" {
			return limitRunes(cleaned, 320)
		}
	}
	return limitRunes(strings.Join(strings.Fields(content), " "), 320)
}

func normalizeDocumentTags(values []string) []string {
	seen := make(map[string]bool)
	tags := make([]string, 0, len(values))
	for _, value := range values {
		tag := cleanDocumentTitle(value)
		key := strings.ToLower(tag)
		if tag == "" || seen[key] {
			continue
		}
		seen[key] = true
		tags = append(tags, limitRunes(tag, 24))
		if len(tags) >= 10 {
			break
		}
	}
	return tags
}

func documentTextTerms(text string) []string {
	terms := make([]string, 0)
	var token []rune
	flush := func() {
		if len(token) == 0 {
			return
		}
		terms = appendDocumentTokenTerms(terms, string(token))
		token = token[:0]
	}
	for _, r := range strings.ToLower(text) {
		if unicode.IsLetter(r) || unicode.IsNumber(r) {
			token = append(token, r)
		} else {
			flush()
		}
	}
	flush()
	return terms
}

func appendDocumentTokenTerms(terms []string, token string) []string {
	token = strings.TrimSpace(token)
	if token == "" {
		return terms
	}
	runes := []rune(token)
	hasHan := false
	for _, r := range runes {
		if unicode.In(r, unicode.Han) {
			hasHan = true
			break
		}
	}
	if hasHan {
		if len(runes) >= 2 && len(runes) <= 8 {
			terms = append(terms, token)
		}
		if len(runes) > 4 {
			for i := 0; i+2 <= len(runes); i++ {
				terms = append(terms, string(runes[i:i+2]))
			}
		}
		return terms
	}
	if len(runes) >= 3 {
		terms = append(terms, token)
	}
	return terms
}

func documentExcerpt(content, query string, maxRunes int) string {
	content = strings.TrimSpace(content)
	if content == "" {
		return ""
	}
	lower := strings.ToLower(content)
	query = strings.ToLower(strings.TrimSpace(query))
	if query != "" {
		if index := strings.Index(lower, query); index >= 0 {
			runes := []rune(content)
			prefixRunes := len([]rune(content[:index]))
			start := prefixRunes - maxRunes/4
			if start < 0 {
				start = 0
			}
			end := start + maxRunes
			if end > len(runes) {
				end = len(runes)
			}
			return strings.TrimSpace(string(runes[start:end]))
		}
	}
	return limitRunes(strings.Join(strings.Fields(content), " "), maxRunes)
}

func cleanDocumentTitle(value string) string {
	return limitRunes(strings.Join(strings.Fields(strings.TrimSpace(value)), " "), 96)
}

func limitRunes(value string, max int) string {
	value = strings.TrimSpace(value)
	runes := []rune(value)
	if max <= 0 || len(runes) <= max {
		return value
	}
	return strings.TrimSpace(string(runes[:max])) + "..."
}

func uniqueNonEmptyStrings(values []string) []string {
	seen := make(map[string]bool)
	result := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		result = append(result, value)
	}
	return result
}

func documentJSON(value interface{}) string {
	payload, _ := json.Marshal(value)
	return string(payload)
}

func decodeDocumentTags(value string) []string {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	var tags []string
	if err := json.Unmarshal([]byte(value), &tags); err != nil {
		return nil
	}
	return normalizeDocumentTags(tags)
}

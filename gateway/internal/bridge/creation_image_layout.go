package bridge

import (
	"errors"
	"math"
	"strings"
	"unicode/utf8"
)

// ImagePlacement is an execution recipe. Independent review uses the frozen
// creative content and references, never this local generation instruction.
type ImagePlacement struct {
	CompositeMode        string  `json:"composite_mode,omitempty"`
	CenterXPercent       float64 `json:"center_x_percent"`
	CenterYPercent       float64 `json:"center_y_percent"`
	SubjectHeightPercent float64 `json:"subject_height_percent"`
	SubjectPrompt        string  `json:"subject_prompt"`
}

func ValidateImageLayout(layout []ImagePlacement, aspect, kind, purpose string, refs []ImageReferenceContext, style string, bound bool) error {
	if len(layout) == 0 {
		return nil
	}
	invalid := errors.New("无效的局部构图：需要分镜图、单个主体、一个环境和一个身份参考，且区域必须在画幅内")
	if len(layout) != 1 || kind != "image" || purpose != "shot_reference" || style != "" || bound || len(refs) != 2 {
		return invalid
	}
	roles := map[string]int{}
	for _, ref := range refs {
		roles[ref.Role]++
	}
	if roles["environment"] != 1 || roles["identity"] != 1 {
		return invalid
	}
	p := layout[0]
	if p.CompositeMode != "" && p.CompositeMode != "foreground_v1" && p.CompositeMode != "foreground_v2" {
		return invalid
	}
	for _, n := range []float64{p.CenterXPercent, p.CenterYPercent, p.SubjectHeightPercent} {
		if math.IsNaN(n) || math.IsInf(n, 0) {
			return invalid
		}
	}
	if p.CenterXPercent < 0 || p.CenterXPercent > 100 || p.CenterYPercent < 0 || p.CenterYPercent > 100 || p.SubjectHeightPercent < 3 || p.SubjectHeightPercent > 25 || strings.TrimSpace(p.SubjectPrompt) == "" || utf8.RuneCountInString(p.SubjectPrompt) > 1800 {
		return invalid
	}
	width, height := 1024.0, 1024.0
	switch aspect {
	case "1:1":
	case "16:9":
		height = 576
	case "9:16":
		width = 576
	default:
		return invalid
	}
	half := math.Ceil(height * p.SubjectHeightPercent / 100 / .74 / 2)
	cx, cy := math.Floor(width*p.CenterXPercent/100+.5), math.Floor(height*p.CenterYPercent/100+.5)
	if cx-half < 0 || cy-half < 0 || cx+half > width || cy+half > height {
		return invalid
	}
	return nil
}

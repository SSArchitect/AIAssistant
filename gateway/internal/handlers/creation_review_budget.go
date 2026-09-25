package handlers

import "reflect"

// The first image batch may be followed by at most five quality repairs.
// History belongs to the node revision, so resuming an automatic request does
// not reset the budget, while an actual user edit starts a new comparison.
const maxAutomaticImageRetries = 5

type creativeImageReview struct {
	Revision          int      `json:"revision"`
	Retries           int      `json:"retries"`
	CandidateIDs      []string `json:"candidate_ids"`
	Compared          int      `json:"compared"`
	BestAssetID       string   `json:"best_asset_id,omitempty"`
	PendingGeneration bool     `json:"pending_generation,omitempty"`
}

func imageReviewHistory(doc *creativeDocument, nodeID string, candidates []string) *creativeImageReview {
	if doc.Automation.ImageReviews == nil {
		doc.Automation.ImageReviews = map[string]*creativeImageReview{}
	}
	history := doc.Automation.ImageReviews[nodeID]
	revision := doc.States[nodeID].Revision
	if history == nil {
		history = &creativeImageReview{Revision: revision, Retries: doc.Automation.RepairCounts[nodeID]}
		// Upgrade older interrupted workflows without granting five more retries.
		for _, repair := range doc.Automation.Repairs {
			if repair.NodeID == nodeID {
				history.CandidateIDs = appendUniqueCreativeCandidates(history.CandidateIDs, repair.CandidateIDs)
			}
		}
	} else if history.Revision != revision {
		history = &creativeImageReview{Revision: revision}
		delete(doc.Automation.RepairCounts, nodeID)
	}
	history.CandidateIDs = appendUniqueCreativeCandidates(history.CandidateIDs, candidates)
	if len(candidates) > 0 {
		history.PendingGeneration = false
	}
	doc.Automation.ImageReviews[nodeID] = history
	return history
}

// A user may delete an old candidate between automatic runs. Skip missing
// historical assets, while leaving required upstream references to the normal
// input validation. Only this account's surviving image assets are eligible.
func (h *CreationHandler) availableImageReviewHistory(user string, history *creativeImageReview) error {
	if len(history.CandidateIDs) == 0 {
		return nil
	}
	var ids []string
	err := h.db.Table("creation_assets").Select("creation_assets.id").
		Joins("JOIN drive_items ON drive_items.id = creation_assets.drive_item_id AND drive_items.user_id = creation_assets.user_id").
		Where("creation_assets.user_id = ? AND creation_assets.id IN ? AND drive_items.mime_type LIKE ?", user, history.CandidateIDs, "image/%").Scan(&ids).Error
	if err != nil {
		return err
	}
	available := map[string]bool{}
	for _, id := range ids {
		available[id] = true
	}
	filtered := []string{}
	for _, id := range history.CandidateIDs {
		if available[id] {
			filtered = append(filtered, id)
		}
	}
	if !reflect.DeepEqual(filtered, history.CandidateIDs) {
		history.CandidateIDs = filtered
		history.Compared, history.BestAssetID = 0, ""
	}
	return nil
}

// Automatic changes to prerequisites may invalidate downstream revisions, but
// they are still the same creative task. Recompare against the updated context
// without silently granting another five image repairs.
func syncAutomaticImageReviewRevisions(doc *creativeDocument) {
	for id, history := range doc.Automation.ImageReviews {
		if state, ok := doc.States[id]; ok && state.Revision != history.Revision {
			history.Revision = state.Revision
			history.Compared, history.BestAssetID = 0, ""
		}
	}
}

func appendUniqueCreativeCandidates(existing, candidates []string) []string {
	seen := map[string]bool{}
	for _, id := range existing {
		seen[id] = true
	}
	for _, id := range candidates {
		if id != "" && !seen[id] {
			existing = append(existing, id)
			seen[id] = true
		}
	}
	return existing
}

// Compare at most three new candidates with the previous winner. This visits
// every saved candidate, leaves preview space for references, and checkpoints
// each comparison so a stop/restart does not repeat completed work.
func bestImageReviewBatch(history *creativeImageReview) ([]string, int) {
	end := history.Compared + 3
	if end > len(history.CandidateIDs) {
		end = len(history.CandidateIDs)
	}
	ids := append([]string{}, history.CandidateIDs[history.Compared:end]...)
	if history.BestAssetID != "" {
		ids = appendUniqueCreativeCandidates(ids, []string{history.BestAssetID})
	}
	return ids, end
}

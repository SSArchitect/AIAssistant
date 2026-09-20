package handlers

import "github.com/aan/agent-assistant-gateway/internal/bridge"

// Acceptance criteria are separate from mutable generation instructions. They
// survive automatic repair and resume, but a user plan edit invalidates them.
type creativeReviewContract struct {
	Revision int    `json:"revision"`
	Content  string `json:"content"`
	Prompt   string `json:"prompt"`
}

func captureReviewContract(doc *creativeDocument, node bridge.CreativeNode) {
	if node.Kind != "image" {
		return
	}
	if doc.ReviewContracts == nil {
		doc.ReviewContracts = map[string]creativeReviewContract{}
	}
	if _, exists := doc.ReviewContracts[node.ID]; !exists {
		doc.ReviewContracts[node.ID] = creativeReviewContract{Revision: doc.States[node.ID].Revision, Content: node.Content, Prompt: node.Prompt}
	}
}

func applyAutomaticRepair(doc creativeDocument, plan bridge.CreativePlan) creativeDocument {
	// Even an unrelated branch can be invalidated by a dependency update. Preserve
	// its contract too; changing execution must not silently change the goal.
	for _, node := range doc.Plan.Nodes {
		captureReviewContract(&doc, node)
	}
	contracts := doc.ReviewContracts
	for i, node := range plan.Nodes {
		if contract, exists := contracts[node.ID]; exists && node.Kind == "image" {
			plan.Nodes[i].Content = contract.Content
		}
	}
	history := doc.Automation
	doc = applyCreativePlan(doc, plan)
	// An automatic repair changes execution, not the user's creative goal. Keep
	// its past failures so changing prompts cannot reset the retry strategy.
	doc.Automation = history
	doc.ReviewContracts = contracts
	return doc
}

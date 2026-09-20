package handlers

import "github.com/aan/agent-assistant-gateway/internal/bridge"

// Copy before filtering: plan application must not mutate the previous snapshot.
func filterCreativeRepairHistory(previous *creativeAutomation, keep func(string) bool) *creativeAutomation {
	if previous == nil {
		return nil
	}
	next := *previous
	next.RepairCounts = map[string]int{}
	next.Repairs = []bridge.CreationRepairFeedback{}
	for id, count := range previous.RepairCounts {
		if count > 0 && keep(id) {
			next.RepairCounts[id] = count
		}
	}
	for _, repair := range previous.Repairs {
		if keep(repair.NodeID) {
			next.Repairs = append(next.Repairs, repair)
		}
	}
	return &next
}

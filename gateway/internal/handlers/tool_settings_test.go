package handlers

import "testing"

func TestValidateUserToolPolicySetting(t *testing.T) {
	for _, policy := range []string{"auto", "confirm", "deny", " CONFIRM "} {
		if err := validateUserToolSetting("tool.delete_drive.policy", policy); err != nil {
			t.Fatalf("expected policy %q to be valid: %v", policy, err)
		}
	}
	if err := validateUserToolSetting("tool.delete_drive.policy", "sometimes"); err == nil {
		t.Fatal("expected unsupported policy to be rejected")
	}
}

func TestToolPoliciesFromSettings(t *testing.T) {
	policies := toolPoliciesFromSettings(map[string]string{
		"tool.delete_drive.policy": "confirm",
		"tool.search.policy":       "deny",
		"tool.search.enabled":      "false",
	})
	if policies["delete_drive"] != "confirm" || policies["search"] != "deny" {
		t.Fatalf("unexpected policies: %#v", policies)
	}
	if len(policies) != 2 {
		t.Fatalf("expected only policy settings, got %#v", policies)
	}
}

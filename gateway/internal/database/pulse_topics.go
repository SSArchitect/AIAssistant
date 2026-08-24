package database

import "gorm.io/gorm"

// Older databases may contain an exclusion column that is no longer part of
// the Topic model. Remove rows marked by that column before serving requests.
func migrateLegacyPulseTopics(db *gorm.DB) error {
	if !db.Migrator().HasColumn("pulse_topics", "enabled") {
		return nil
	}
	return db.Exec("DELETE FROM pulse_topics WHERE enabled = ?", false).Error
}

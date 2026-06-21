package handlers

import (
	"strings"

	"github.com/gin-gonic/gin"
)

func normalizedUserID(userID string) string {
	userID = strings.TrimSpace(userID)
	if userID == "" {
		return "0"
	}
	return userID
}

func requestUserID(c *gin.Context) string {
	for _, token := range []string{
		c.GetHeader("X-Account-Session"),
		c.Query("account_session"),
	} {
		if userID, ok := accountSessionUserID(token); ok {
			return userID
		}
	}
	for _, value := range []string{
		c.Query("user_id"),
		c.Query("account_id"),
		c.GetHeader("X-User-ID"),
		c.GetHeader("X-Account-ID"),
	} {
		if strings.TrimSpace(value) != "" {
			return normalizedUserID(value)
		}
	}
	return "0"
}

func requestUserIDWithBody(c *gin.Context, bodyUserID string) string {
	for _, token := range []string{
		c.GetHeader("X-Account-Session"),
		c.Query("account_session"),
	} {
		if userID, ok := accountSessionUserID(token); ok {
			return userID
		}
	}
	if strings.TrimSpace(bodyUserID) != "" {
		return normalizedUserID(bodyUserID)
	}
	for _, value := range []string{
		c.Query("user_id"),
		c.Query("account_id"),
		c.GetHeader("X-User-ID"),
		c.GetHeader("X-Account-ID"),
	} {
		if strings.TrimSpace(value) != "" {
			return normalizedUserID(value)
		}
	}
	return "0"
}

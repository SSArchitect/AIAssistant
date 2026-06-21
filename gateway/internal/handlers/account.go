package handlers

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"net/http"
	"strings"
	"time"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"golang.org/x/crypto/bcrypt"
)

type AccountHandler struct{}

type accountCreateRequest struct {
	ID       string `json:"id,omitempty"`
	Name     string `json:"name" binding:"required"`
	Password string `json:"password" binding:"required"`
}

type accountLoginRequest struct {
	ID       string `json:"id" binding:"required"`
	Password string `json:"password" binding:"required"`
}

type accountResponse struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	PasswordSet bool      `json:"password_set"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

type accountAuthResponse struct {
	Account accountResponse `json:"account"`
	Token   string          `json:"token"`
}

func NewAccountHandler() *AccountHandler {
	return &AccountHandler{}
}

func (h *AccountHandler) List(c *gin.Context) {
	var accounts []models.Account
	if err := database.DB.Order("created_at asc").Find(&accounts).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load accounts"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"accounts": accountResponses(accounts)})
}

func (h *AccountHandler) Create(c *gin.Context) {
	var req accountCreateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	name := strings.TrimSpace(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "account name is required"})
		return
	}
	password := strings.TrimSpace(req.Password)
	if err := validateAccountPassword(password); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	passwordHash, err := hashAccountPassword(password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to secure account password"})
		return
	}

	id := normalizedAccountID(req.ID)
	if id == "" {
		id = uuid.NewString()
	}

	now := time.Now()
	account := models.Account{
		ID:           id,
		Name:         name,
		PasswordHash: passwordHash,
		CreatedAt:    now,
		UpdatedAt:    now,
	}
	if err := database.DB.Create(&account).Error; err != nil {
		c.JSON(http.StatusConflict, gin.H{"error": "failed to create account: " + err.Error()})
		return
	}
	token, err := createAccountSession(account.ID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "account created, but login session failed"})
		return
	}
	c.JSON(http.StatusCreated, accountAuthResponse{
		Account: toAccountResponse(account),
		Token:   token,
	})
}

func (h *AccountHandler) Login(c *gin.Context) {
	var req accountLoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	password := strings.TrimSpace(req.Password)
	if err := validateAccountPassword(password); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	var account models.Account
	if err := database.DB.First(&account, "id = ?", normalizedUserID(req.ID)).Error; err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "account or password is incorrect"})
		return
	}

	if account.PasswordHash == "" {
		passwordHash, err := hashAccountPassword(password)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to secure account password"})
			return
		}
		account.PasswordHash = passwordHash
		account.UpdatedAt = time.Now()
		if err := database.DB.Save(&account).Error; err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to set account password"})
			return
		}
	} else if err := bcrypt.CompareHashAndPassword([]byte(account.PasswordHash), []byte(password)); err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "account or password is incorrect"})
		return
	}

	token, err := createAccountSession(account.ID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create login session"})
		return
	}
	c.JSON(http.StatusOK, accountAuthResponse{
		Account: toAccountResponse(account),
		Token:   token,
	})
}

func normalizedAccountID(value string) string {
	value = strings.TrimSpace(value)
	value = strings.Map(func(r rune) rune {
		switch {
		case r >= 'a' && r <= 'z':
			return r
		case r >= 'A' && r <= 'Z':
			return r
		case r >= '0' && r <= '9':
			return r
		case r == '-' || r == '_':
			return r
		default:
			return -1
		}
	}, value)
	return strings.Trim(value, "-_")
}

func validateAccountPassword(password string) error {
	if len([]rune(password)) < 4 {
		return errAccountPasswordTooShort{}
	}
	return nil
}

type errAccountPasswordTooShort struct{}

func (errAccountPasswordTooShort) Error() string {
	return "password must be at least 4 characters"
}

func hashAccountPassword(password string) (string, error) {
	hashed, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(hashed), nil
}

func createAccountSession(userID string) (string, error) {
	bytes := make([]byte, 32)
	if _, err := rand.Read(bytes); err != nil {
		return "", err
	}
	token := base64.RawURLEncoding.EncodeToString(bytes)
	now := time.Now()
	session := models.AccountSession{
		TokenHash:  accountSessionTokenHash(token),
		UserID:     normalizedUserID(userID),
		CreatedAt:  now,
		LastUsedAt: now,
	}
	if err := database.DB.Create(&session).Error; err != nil {
		return "", err
	}
	return token, nil
}

func accountSessionUserID(token string) (string, bool) {
	token = strings.TrimSpace(token)
	if token == "" {
		return "", false
	}
	var session models.AccountSession
	if err := database.DB.First(&session, "token_hash = ?", accountSessionTokenHash(token)).Error; err != nil {
		return "", false
	}
	database.DB.Model(&session).Update("last_used_at", time.Now())
	return normalizedUserID(session.UserID), true
}

func accountSessionTokenHash(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

func accountResponses(accounts []models.Account) []accountResponse {
	responses := make([]accountResponse, 0, len(accounts))
	for _, account := range accounts {
		responses = append(responses, toAccountResponse(account))
	}
	return responses
}

func toAccountResponse(account models.Account) accountResponse {
	return accountResponse{
		ID:          account.ID,
		Name:        account.Name,
		PasswordSet: account.PasswordHash != "",
		CreatedAt:   account.CreatedAt,
		UpdatedAt:   account.UpdatedAt,
	}
}

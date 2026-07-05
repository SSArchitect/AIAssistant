package handlers

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/aan/agent-assistant-gateway/internal/database"
	"github.com/aan/agent-assistant-gateway/internal/models"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"gorm.io/gorm"
)

const (
	knowledgeDefaultProjectName = "Untitled Project"
	knowledgeDefaultDocType     = "source"
	knowledgeMaxContentRunes    = 220000
	knowledgeContextDocLimit    = 8
)

type KnowledgeHandler struct{}

func NewKnowledgeHandler() *KnowledgeHandler {
	return &KnowledgeHandler{}
}

type knowledgeProjectRequest struct {
	UserID      string `json:"user_id,omitempty"`
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
}

type knowledgeProjectOrderRequest struct {
	UserID     string   `json:"user_id,omitempty"`
	ProjectIDs []string `json:"project_ids"`
}

type knowledgeDocumentRequest struct {
	UserID           string   `json:"user_id,omitempty"`
	Title            string   `json:"title"`
	Type             string   `json:"type,omitempty"`
	SourceName       string   `json:"source_name,omitempty"`
	SourceDocumentID string   `json:"source_document_id,omitempty"`
	Summary          string   `json:"summary,omitempty"`
	Tags             []string `json:"tags,omitempty"`
	Content          string   `json:"content"`
}

type knowledgeContextRequest struct {
	UserID      string   `json:"user_id,omitempty"`
	Query       string   `json:"query,omitempty"`
	DocumentIDs []string `json:"document_ids,omitempty"`
}

type knowledgeSelectionRequest struct {
	UserID      string   `json:"user_id,omitempty"`
	Name        string   `json:"name"`
	Description string   `json:"description,omitempty"`
	DocumentIDs []string `json:"document_ids"`
}

type knowledgeProjectResponse struct {
	ID            string    `json:"id"`
	UserID        string    `json:"user_id"`
	Name          string    `json:"name"`
	Description   string    `json:"description,omitempty"`
	SortOrder     int       `json:"sort_order"`
	DocumentCount int       `json:"document_count"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

type knowledgeDocumentResponse struct {
	ID               string    `json:"id"`
	UserID           string    `json:"user_id"`
	ProjectID        string    `json:"project_id"`
	SourceDocumentID string    `json:"source_document_id,omitempty"`
	Type             string    `json:"type"`
	Title            string    `json:"title"`
	SourceName       string    `json:"source_name,omitempty"`
	Summary          string    `json:"summary"`
	Tags             []string  `json:"tags"`
	Content          string    `json:"content,omitempty"`
	CreatedAt        time.Time `json:"created_at"`
	UpdatedAt        time.Time `json:"updated_at"`
}

type knowledgeLinkResponse struct {
	ID             string    `json:"id"`
	UserID         string    `json:"user_id"`
	ProjectID      string    `json:"project_id"`
	FromDocumentID string    `json:"from_document_id"`
	ToDocumentID   string    `json:"to_document_id"`
	Relation       string    `json:"relation"`
	Explanation    string    `json:"explanation,omitempty"`
	Confidence     int       `json:"confidence"`
	CreatedAt      time.Time `json:"created_at"`
	UpdatedAt      time.Time `json:"updated_at"`
}

type knowledgeMapResponse struct {
	Nodes []knowledgeDocumentResponse `json:"nodes"`
	Edges []knowledgeLinkResponse     `json:"edges"`
}

type knowledgeProjectDetailResponse struct {
	Project   knowledgeProjectResponse    `json:"project"`
	Documents []knowledgeDocumentResponse `json:"documents"`
	Links     []knowledgeLinkResponse     `json:"links"`
	Map       knowledgeMapResponse        `json:"map"`
}

type knowledgeSearchResult struct {
	Document knowledgeDocumentResponse `json:"document"`
	Score    int                       `json:"score"`
	Snippet  string                    `json:"snippet"`
}

func (h *KnowledgeHandler) List(c *gin.Context) {
	userID := requestUserID(c)
	projects, counts, err := loadKnowledgeProjects(userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load projects"})
		return
	}

	responses := make([]knowledgeProjectResponse, 0, len(projects))
	for _, project := range projects {
		responses = append(responses, knowledgeProjectFromModel(project, counts[project.ID]))
	}
	c.JSON(http.StatusOK, gin.H{"projects": responses})
}

func (h *KnowledgeHandler) Create(c *gin.Context) {
	var req knowledgeProjectRequest
	_ = c.ShouldBindJSON(&req)
	userID := requestUserIDWithBody(c, req.UserID)
	name := cleanKnowledgeTitle(req.Name)
	if name == "" {
		name = knowledgeDefaultProjectName
	}

	now := time.Now()
	project := models.KnowledgeProject{
		ID:          uuid.New().String(),
		UserID:      userID,
		Name:        name,
		Description: strings.TrimSpace(req.Description),
		SortOrder:   nextKnowledgeProjectSortOrder(userID),
		CreatedAt:   now,
		UpdatedAt:   now,
	}
	if err := database.DB.Create(&project).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create project"})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"project": knowledgeProjectFromModel(project, 0)})
}

func (h *KnowledgeHandler) Update(c *gin.Context) {
	userID := requestUserID(c)
	project, ok := h.loadProject(c, userID)
	if !ok {
		return
	}

	var req knowledgeProjectRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	name := cleanKnowledgeTitle(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "project name is required"})
		return
	}
	project.Name = name
	project.Description = strings.TrimSpace(req.Description)
	project.UpdatedAt = time.Now()
	if err := database.DB.Save(&project).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update project"})
		return
	}
	count := int64(0)
	database.DB.Model(&models.KnowledgeDocument{}).Where("project_id = ? AND user_id = ?", project.ID, userID).Count(&count)
	c.JSON(http.StatusOK, gin.H{"project": knowledgeProjectFromModel(project, int(count))})
}

func (h *KnowledgeHandler) Reorder(c *gin.Context) {
	var req knowledgeProjectOrderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)
	seen := make(map[string]bool)
	err := database.DB.Transaction(func(tx *gorm.DB) error {
		for index, id := range req.ProjectIDs {
			id = strings.TrimSpace(id)
			if id == "" || seen[id] {
				continue
			}
			seen[id] = true
			if err := tx.Model(&models.KnowledgeProject{}).
				Where("id = ? AND user_id = ?", id, userID).
				Updates(map[string]interface{}{"sort_order": index, "updated_at": time.Now()}).Error; err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to reorder projects"})
		return
	}
	h.List(c)
}

func (h *KnowledgeHandler) Delete(c *gin.Context) {
	userID := requestUserID(c)
	project, ok := h.loadProject(c, userID)
	if !ok {
		return
	}
	err := database.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Where("project_id = ? AND user_id = ?", project.ID, userID).Delete(&models.KnowledgeLink{}).Error; err != nil {
			return err
		}
		if err := tx.Where("project_id = ? AND user_id = ?", project.ID, userID).Delete(&models.KnowledgeDocument{}).Error; err != nil {
			return err
		}
		return tx.Delete(&models.KnowledgeProject{}, "id = ? AND user_id = ?", project.ID, userID).Error
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete project"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}

func (h *KnowledgeHandler) Get(c *gin.Context) {
	userID := requestUserID(c)
	project, ok := h.loadProject(c, userID)
	if !ok {
		return
	}
	detail, err := h.projectDetail(project, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load project"})
		return
	}
	c.JSON(http.StatusOK, detail)
}

func (h *KnowledgeHandler) CreateDocument(c *gin.Context) {
	userID := requestUserID(c)
	project, ok := h.loadProject(c, userID)
	if !ok {
		return
	}

	var req knowledgeDocumentRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	if bodyUserID := strings.TrimSpace(req.UserID); bodyUserID != "" {
		userID = requestUserIDWithBody(c, bodyUserID)
		if userID != project.UserID {
			c.JSON(http.StatusNotFound, gin.H{"error": "project not found"})
			return
		}
	}
	content := trimKnowledgeContent(req.Content)
	if content == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "document content is required"})
		return
	}
	title := cleanKnowledgeTitle(req.Title)
	if title == "" {
		title = titleFromKnowledgeContent(content, req.SourceName)
	}
	summary := strings.TrimSpace(req.Summary)
	if summary == "" {
		summary = summarizeKnowledgeContent(content)
	}
	tags := normalizeKnowledgeTags(req.Tags)
	if len(tags) == 0 {
		tags = extractKnowledgeTags(title + "\n" + summary + "\n" + content)
	}

	now := time.Now()
	document := models.KnowledgeDocument{
		ID:               uuid.New().String(),
		UserID:           userID,
		ProjectID:        project.ID,
		SourceDocumentID: strings.TrimSpace(req.SourceDocumentID),
		Type:             normalizeKnowledgeDocType(req.Type),
		Title:            title,
		SourceName:       strings.TrimSpace(req.SourceName),
		Summary:          summary,
		TagsJSON:         knowledgeJSON(tags),
		Content:          content,
		CreatedAt:        now,
		UpdatedAt:        now,
	}

	if err := database.DB.Create(&document).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create document"})
		return
	}
	if err := rebuildKnowledgeProjectLinks(project.ID, userID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "document saved, but map rebuild failed"})
		return
	}
	database.DB.Model(&project).Update("updated_at", time.Now())
	c.JSON(http.StatusCreated, gin.H{"document": knowledgeDocumentFromModel(document)})
}

func (h *KnowledgeHandler) DeleteDocument(c *gin.Context) {
	userID := requestUserID(c)
	project, ok := h.loadProject(c, userID)
	if !ok {
		return
	}
	documentID := strings.TrimSpace(c.Param("document_id"))
	if documentID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "document id is required"})
		return
	}

	err := database.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Where(
			"project_id = ? AND user_id = ? AND (from_document_id = ? OR to_document_id = ?)",
			project.ID,
			userID,
			documentID,
			documentID,
		).Delete(&models.KnowledgeLink{}).Error; err != nil {
			return err
		}
		result := tx.Delete(&models.KnowledgeDocument{}, "id = ? AND project_id = ? AND user_id = ?", documentID, project.ID, userID)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return gorm.ErrRecordNotFound
		}
		return tx.Model(&project).Update("updated_at", time.Now()).Error
	})
	if errors.Is(err, gorm.ErrRecordNotFound) {
		c.JSON(http.StatusNotFound, gin.H{"error": "document not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete document"})
		return
	}
	if err := rebuildKnowledgeProjectLinks(project.ID, userID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "document deleted, but map rebuild failed"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}

func (h *KnowledgeHandler) Search(c *gin.Context) {
	userID := requestUserID(c)
	project, ok := h.loadProject(c, userID)
	if !ok {
		return
	}
	query := strings.TrimSpace(c.Query("q"))
	documents, err := loadKnowledgeDocuments(project.ID, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to search documents"})
		return
	}
	results := rankedKnowledgeDocuments(documents, query)
	c.JSON(http.StatusOK, gin.H{"results": results})
}

func (h *KnowledgeHandler) Context(c *gin.Context) {
	userID := requestUserID(c)
	project, ok := h.loadProject(c, userID)
	if !ok {
		return
	}

	var req knowledgeContextRequest
	_ = c.ShouldBindJSON(&req)
	if bodyUserID := strings.TrimSpace(req.UserID); bodyUserID != "" {
		userID = requestUserIDWithBody(c, bodyUserID)
		if userID != project.UserID {
			c.JSON(http.StatusNotFound, gin.H{"error": "project not found"})
			return
		}
	}

	documents, err := loadKnowledgeDocuments(project.ID, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to build project context"})
		return
	}
	selected := selectKnowledgeContextDocuments(documents, req.DocumentIDs, req.Query)
	contextBlock := buildKnowledgeContextBlock(project, selected, req.Query)
	c.JSON(http.StatusOK, gin.H{
		"context_blocks": []string{contextBlock},
		"documents":      knowledgeDocumentResponses(selected, true),
	})
}

func (h *KnowledgeHandler) CreateFromSelection(c *gin.Context) {
	var req knowledgeSelectionRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}
	userID := requestUserIDWithBody(c, req.UserID)
	documentIDs := uniqueNonEmptyStrings(req.DocumentIDs)
	if len(documentIDs) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "document selection is required"})
		return
	}

	var sourceDocs []models.KnowledgeDocument
	if err := database.DB.Where("user_id = ? AND id IN ?", userID, documentIDs).Find(&sourceDocs).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to load selected documents"})
		return
	}
	sourceByID := make(map[string]models.KnowledgeDocument, len(sourceDocs))
	for _, doc := range sourceDocs {
		sourceByID[doc.ID] = doc
	}
	orderedSources := make([]models.KnowledgeDocument, 0, len(sourceDocs))
	for _, id := range documentIDs {
		if doc, ok := sourceByID[id]; ok {
			orderedSources = append(orderedSources, doc)
		}
	}
	if len(orderedSources) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "selected documents were not found"})
		return
	}

	name := cleanKnowledgeTitle(req.Name)
	if name == "" {
		name = "Knowledge Selection"
	}
	now := time.Now()
	project := models.KnowledgeProject{
		ID:          uuid.New().String(),
		UserID:      userID,
		Name:        name,
		Description: strings.TrimSpace(req.Description),
		SortOrder:   nextKnowledgeProjectSortOrder(userID),
		CreatedAt:   now,
		UpdatedAt:   now,
	}

	newDocs := make([]models.KnowledgeDocument, 0, len(orderedSources))
	err := database.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&project).Error; err != nil {
			return err
		}
		for _, source := range orderedSources {
			doc := models.KnowledgeDocument{
				ID:               uuid.New().String(),
				UserID:           userID,
				ProjectID:        project.ID,
				SourceDocumentID: source.ID,
				Type:             normalizeKnowledgeDocType(source.Type),
				Title:            source.Title,
				SourceName:       source.SourceName,
				Summary:          source.Summary,
				TagsJSON:         source.TagsJSON,
				Content:          source.Content,
				CreatedAt:        now,
				UpdatedAt:        now,
			}
			newDocs = append(newDocs, doc)
		}
		return tx.Create(&newDocs).Error
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create project from selection"})
		return
	}
	if err := rebuildKnowledgeProjectLinks(project.ID, userID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "project created, but map rebuild failed"})
		return
	}
	detail, err := h.projectDetail(project, userID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "project created, but failed to load details"})
		return
	}
	c.JSON(http.StatusCreated, detail)
}

func (h *KnowledgeHandler) loadProject(c *gin.Context, userID string) (models.KnowledgeProject, bool) {
	id := strings.TrimSpace(c.Param("id"))
	var project models.KnowledgeProject
	if id == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "project id is required"})
		return project, false
	}
	if err := database.DB.First(&project, "id = ? AND user_id = ?", id, userID).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "project not found"})
		return project, false
	}
	return project, true
}

func (h *KnowledgeHandler) projectDetail(project models.KnowledgeProject, userID string) (knowledgeProjectDetailResponse, error) {
	documents, err := loadKnowledgeDocuments(project.ID, userID)
	if err != nil {
		return knowledgeProjectDetailResponse{}, err
	}
	var links []models.KnowledgeLink
	if err := database.DB.Where("project_id = ? AND user_id = ?", project.ID, userID).
		Order("confidence desc, created_at asc").
		Find(&links).Error; err != nil {
		return knowledgeProjectDetailResponse{}, err
	}
	docResponses := knowledgeDocumentResponses(documents, true)
	linkResponses := knowledgeLinkResponses(links)
	return knowledgeProjectDetailResponse{
		Project:   knowledgeProjectFromModel(project, len(documents)),
		Documents: docResponses,
		Links:     linkResponses,
		Map: knowledgeMapResponse{
			Nodes: docResponses,
			Edges: linkResponses,
		},
	}, nil
}

func loadKnowledgeProjects(userID string) ([]models.KnowledgeProject, map[string]int, error) {
	var projects []models.KnowledgeProject
	if err := database.DB.Where("user_id = ?", userID).
		Order("sort_order asc, updated_at desc").
		Find(&projects).Error; err != nil {
		return nil, nil, err
	}
	counts := make(map[string]int, len(projects))
	if len(projects) == 0 {
		return projects, counts, nil
	}
	projectIDs := make([]string, 0, len(projects))
	for _, project := range projects {
		projectIDs = append(projectIDs, project.ID)
	}
	var rows []struct {
		ProjectID string
		Count     int
	}
	if err := database.DB.Model(&models.KnowledgeDocument{}).
		Select("project_id, count(*) as count").
		Where("user_id = ? AND project_id IN ?", userID, projectIDs).
		Group("project_id").
		Scan(&rows).Error; err != nil {
		return nil, nil, err
	}
	for _, row := range rows {
		counts[row.ProjectID] = row.Count
	}
	return projects, counts, nil
}

func nextKnowledgeProjectSortOrder(userID string) int {
	var maxOrder int
	database.DB.Model(&models.KnowledgeProject{}).
		Select("COALESCE(MAX(sort_order), -1)").
		Where("user_id = ?", userID).
		Scan(&maxOrder)
	return maxOrder + 1
}

func loadKnowledgeDocuments(projectID, userID string) ([]models.KnowledgeDocument, error) {
	var documents []models.KnowledgeDocument
	err := database.DB.Where("project_id = ? AND user_id = ?", projectID, userID).
		Order("updated_at desc, created_at desc").
		Find(&documents).Error
	return documents, err
}

func rebuildKnowledgeProjectLinks(projectID, userID string) error {
	documents, err := loadKnowledgeDocuments(projectID, userID)
	if err != nil {
		return err
	}
	now := time.Now()
	links := make([]models.KnowledgeLink, 0)
	for i := 0; i < len(documents); i++ {
		for j := i + 1; j < len(documents); j++ {
			link, ok := inferKnowledgeLink(projectID, userID, documents[i], documents[j], now)
			if ok {
				links = append(links, link)
			}
		}
	}
	return database.DB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Where("project_id = ? AND user_id = ?", projectID, userID).Delete(&models.KnowledgeLink{}).Error; err != nil {
			return err
		}
		if len(links) == 0 {
			return nil
		}
		return tx.Create(&links).Error
	})
}

func inferKnowledgeLink(projectID, userID string, a, b models.KnowledgeDocument, now time.Time) (models.KnowledgeLink, bool) {
	fromID := a.ID
	toID := b.ID
	relation := ""
	explanation := ""
	confidence := 0

	if a.SourceDocumentID == b.ID {
		relation = "沉淀自"
		fromID, toID = b.ID, a.ID
		explanation = fmt.Sprintf("《%s》由《%s》沉淀或复制而来。", a.Title, b.Title)
		confidence = 95
	} else if b.SourceDocumentID == a.ID {
		relation = "沉淀自"
		fromID, toID = a.ID, b.ID
		explanation = fmt.Sprintf("《%s》由《%s》沉淀或复制而来。", b.Title, a.Title)
		confidence = 95
	} else if titleReferencesDocument(a, b) {
		relation = "引用"
		fromID, toID = a.ID, b.ID
		explanation = fmt.Sprintf("《%s》的内容提到了《%s》。", a.Title, b.Title)
		confidence = 82
	} else if titleReferencesDocument(b, a) {
		relation = "引用"
		fromID, toID = b.ID, a.ID
		explanation = fmt.Sprintf("《%s》的内容提到了《%s》。", b.Title, a.Title)
		confidence = 82
	} else {
		score, shared := knowledgeDocumentSimilarity(a, b)
		if score < 0.22 || len(shared) < 2 {
			return models.KnowledgeLink{}, false
		}
		relation = "相关"
		if score >= 0.46 {
			relation = "高度相关"
		}
		confidence = 55 + int(score*40)
		if confidence > 92 {
			confidence = 92
		}
		explanation = fmt.Sprintf("共享关键词：%s。", strings.Join(limitStringSlice(shared, 5, 24), " / "))
	}

	return models.KnowledgeLink{
		ID:             uuid.New().String(),
		UserID:         userID,
		ProjectID:      projectID,
		FromDocumentID: fromID,
		ToDocumentID:   toID,
		Relation:       relation,
		Explanation:    explanation,
		Confidence:     confidence,
		CreatedAt:      now,
		UpdatedAt:      now,
	}, true
}

func titleReferencesDocument(source, target models.KnowledgeDocument) bool {
	title := strings.TrimSpace(target.Title)
	if title == "" || len([]rune(title)) < 4 {
		return false
	}
	haystack := strings.ToLower(source.Title + "\n" + source.Summary + "\n" + source.Content)
	return strings.Contains(haystack, strings.ToLower(title))
}

func knowledgeDocumentSimilarity(a, b models.KnowledgeDocument) (float64, []string) {
	aTerms := documentKnowledgeTermSet(a)
	bTerms := documentKnowledgeTermSet(b)
	if len(aTerms) == 0 || len(bTerms) == 0 {
		return 0, nil
	}
	shared := make([]string, 0)
	for term := range aTerms {
		if bTerms[term] {
			shared = append(shared, term)
		}
	}
	sort.Slice(shared, func(i, j int) bool {
		if len([]rune(shared[i])) != len([]rune(shared[j])) {
			return len([]rune(shared[i])) > len([]rune(shared[j]))
		}
		return shared[i] < shared[j]
	})
	smaller := len(aTerms)
	if len(bTerms) < smaller {
		smaller = len(bTerms)
	}
	if smaller == 0 {
		return 0, shared
	}
	return float64(len(shared)) / float64(smaller), shared
}

func documentKnowledgeTermSet(doc models.KnowledgeDocument) map[string]bool {
	terms := decodeKnowledgeTags(doc.TagsJSON)
	terms = append(terms, knowledgeTextTerms(doc.Title)...)
	terms = append(terms, knowledgeTextTerms(doc.Summary)...)
	if len(terms) < 24 {
		terms = append(terms, extractKnowledgeTags(doc.Content)...)
	}
	set := make(map[string]bool)
	for _, term := range terms {
		term = normalizeKnowledgeTerm(term)
		if term != "" {
			set[term] = true
		}
	}
	return set
}

func rankedKnowledgeDocuments(documents []models.KnowledgeDocument, query string) []knowledgeSearchResult {
	terms := uniqueNonEmptyStrings(knowledgeTextTerms(query))
	results := make([]knowledgeSearchResult, 0, len(documents))
	for _, doc := range documents {
		score := knowledgeDocumentSearchScore(doc, query, terms)
		if strings.TrimSpace(query) != "" && score <= 0 {
			continue
		}
		results = append(results, knowledgeSearchResult{
			Document: knowledgeDocumentFromModel(doc),
			Score:    score,
			Snippet:  knowledgeExcerpt(doc.Content, query, 240),
		})
	}
	sort.SliceStable(results, func(i, j int) bool {
		if results[i].Score != results[j].Score {
			return results[i].Score > results[j].Score
		}
		return results[i].Document.UpdatedAt.After(results[j].Document.UpdatedAt)
	})
	if len(results) > 30 {
		return results[:30]
	}
	return results
}

func knowledgeDocumentSearchScore(doc models.KnowledgeDocument, query string, terms []string) int {
	query = strings.ToLower(strings.TrimSpace(query))
	if query == "" {
		return 1
	}
	score := 0
	title := strings.ToLower(doc.Title)
	summary := strings.ToLower(doc.Summary)
	content := strings.ToLower(doc.Content)
	tags := decodeKnowledgeTags(doc.TagsJSON)
	if strings.Contains(title, query) {
		score += 80
	}
	if strings.Contains(summary, query) {
		score += 40
	}
	if strings.Contains(content, query) {
		score += 24
	}
	for _, tag := range tags {
		tag = strings.ToLower(tag)
		if tag == query {
			score += 45
		} else if strings.Contains(tag, query) || strings.Contains(query, tag) {
			score += 24
		}
	}
	for _, term := range terms {
		if term == "" {
			continue
		}
		if strings.Contains(title, term) {
			score += 18
		}
		if strings.Contains(summary, term) {
			score += 10
		}
		if strings.Contains(content, term) {
			score += 4
		}
		for _, tag := range tags {
			if strings.Contains(strings.ToLower(tag), term) {
				score += 8
				break
			}
		}
	}
	return score
}

func selectKnowledgeContextDocuments(documents []models.KnowledgeDocument, documentIDs []string, query string) []models.KnowledgeDocument {
	selectedIDs := make(map[string]bool)
	for _, id := range documentIDs {
		id = strings.TrimSpace(id)
		if id != "" {
			selectedIDs[id] = true
		}
	}
	if len(selectedIDs) > 0 {
		selected := make([]models.KnowledgeDocument, 0, len(selectedIDs))
		for _, doc := range documents {
			if selectedIDs[doc.ID] {
				selected = append(selected, doc)
			}
		}
		if len(selected) > knowledgeContextDocLimit {
			return selected[:knowledgeContextDocLimit]
		}
		return selected
	}

	results := rankedKnowledgeDocuments(documents, query)
	selected := make([]models.KnowledgeDocument, 0, knowledgeContextDocLimit)
	for _, result := range results {
		if len(selected) >= knowledgeContextDocLimit {
			break
		}
		selected = append(selected, documentFromResponse(result.Document))
	}
	if len(selected) > 0 {
		return selected
	}
	if len(documents) > knowledgeContextDocLimit {
		return documents[:knowledgeContextDocLimit]
	}
	return documents
}

func buildKnowledgeContextBlock(project models.KnowledgeProject, documents []models.KnowledgeDocument, query string) string {
	lines := []string{
		"[Project Knowledge Context]",
		"Use this project context as grounded reference material. Prefer citing document titles when answering.",
		fmt.Sprintf("Project: %s", project.Name),
	}
	if project.Description != "" {
		lines = append(lines, fmt.Sprintf("Description: %s", project.Description))
	}
	if strings.TrimSpace(query) != "" {
		lines = append(lines, fmt.Sprintf("User focus: %s", strings.TrimSpace(query)))
	}
	lines = append(lines, "", "Documents:")
	for index, doc := range documents {
		tags := decodeKnowledgeTags(doc.TagsJSON)
		lines = append(lines,
			fmt.Sprintf("## %d. %s", index+1, doc.Title),
			fmt.Sprintf("ID: %s", doc.ID),
			fmt.Sprintf("Type: %s", doc.Type),
		)
		if len(tags) > 0 {
			lines = append(lines, fmt.Sprintf("Tags: %s", strings.Join(tags, " / ")))
		}
		if doc.Summary != "" {
			lines = append(lines, fmt.Sprintf("Summary: %s", doc.Summary))
		}
		excerpt := knowledgeExcerpt(doc.Content, query, 900)
		if excerpt != "" {
			lines = append(lines, "Excerpt:", excerpt)
		}
		lines = append(lines, "")
	}
	return strings.TrimSpace(strings.Join(lines, "\n"))
}

func documentFromResponse(resp knowledgeDocumentResponse) models.KnowledgeDocument {
	return models.KnowledgeDocument{
		ID:               resp.ID,
		UserID:           resp.UserID,
		ProjectID:        resp.ProjectID,
		SourceDocumentID: resp.SourceDocumentID,
		Type:             resp.Type,
		Title:            resp.Title,
		SourceName:       resp.SourceName,
		Summary:          resp.Summary,
		TagsJSON:         knowledgeJSON(resp.Tags),
		Content:          resp.Content,
		CreatedAt:        resp.CreatedAt,
		UpdatedAt:        resp.UpdatedAt,
	}
}

func cleanKnowledgeTitle(value string) string {
	return limitRunes(strings.Join(strings.Fields(strings.TrimSpace(value)), " "), 96)
}

func trimKnowledgeContent(value string) string {
	value = strings.TrimSpace(strings.ReplaceAll(value, "\u0000", ""))
	return limitRunes(value, knowledgeMaxContentRunes)
}

func titleFromKnowledgeContent(content, fallback string) string {
	for _, line := range strings.Split(content, "\n") {
		line = strings.TrimSpace(strings.TrimLeft(line, "#>-*0123456789. "))
		if line != "" {
			return cleanKnowledgeTitle(line)
		}
	}
	if cleaned := cleanKnowledgeTitle(fallback); cleaned != "" {
		return cleaned
	}
	return "Untitled Document"
}

func summarizeKnowledgeContent(content string) string {
	paragraphs := strings.Split(strings.ReplaceAll(content, "\r\n", "\n"), "\n\n")
	for _, paragraph := range paragraphs {
		cleaned := strings.Join(strings.Fields(paragraph), " ")
		if cleaned != "" {
			return limitRunes(cleaned, 320)
		}
	}
	return limitRunes(strings.Join(strings.Fields(content), " "), 320)
}

func normalizeKnowledgeDocType(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "source", "note", "generated", "summary":
		return strings.ToLower(strings.TrimSpace(value))
	default:
		return knowledgeDefaultDocType
	}
}

func normalizeKnowledgeTags(values []string) []string {
	seen := make(map[string]bool)
	tags := make([]string, 0, len(values))
	for _, value := range values {
		tag := cleanKnowledgeTitle(value)
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

func extractKnowledgeTags(text string) []string {
	counts := make(map[string]int)
	for _, term := range knowledgeTextTerms(text) {
		term = normalizeKnowledgeTerm(term)
		if term == "" {
			continue
		}
		counts[term]++
	}
	type scoredTerm struct {
		Term  string
		Score int
	}
	scored := make([]scoredTerm, 0, len(counts))
	for term, count := range counts {
		score := count * (1 + len([]rune(term))/4)
		scored = append(scored, scoredTerm{Term: term, Score: score})
	}
	sort.Slice(scored, func(i, j int) bool {
		if scored[i].Score != scored[j].Score {
			return scored[i].Score > scored[j].Score
		}
		return scored[i].Term < scored[j].Term
	})
	tags := make([]string, 0, 8)
	for _, item := range scored {
		tags = append(tags, item.Term)
		if len(tags) >= 8 {
			break
		}
	}
	return tags
}

func knowledgeTextTerms(text string) []string {
	terms := make([]string, 0)
	var token []rune
	flush := func() {
		if len(token) == 0 {
			return
		}
		terms = appendKnowledgeTokenTerms(terms, string(token))
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

func appendKnowledgeTokenTerms(terms []string, token string) []string {
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

func normalizeKnowledgeTerm(term string) string {
	term = strings.ToLower(strings.TrimSpace(term))
	if term == "" || knowledgeStopWords[term] {
		return ""
	}
	if len([]rune(term)) > 28 {
		return ""
	}
	return term
}

var knowledgeStopWords = map[string]bool{
	"the": true, "and": true, "for": true, "with": true, "that": true, "this": true, "from": true,
	"are": true, "was": true, "were": true, "have": true, "has": true, "not": true, "you": true,
	"一个": true, "这个": true, "那个": true, "以及": true, "因为": true, "所以": true, "但是": true,
	"进行": true, "可以": true, "需要": true, "用户": true, "文档": true, "项目": true, "知识": true,
}

func knowledgeExcerpt(content, query string, maxRunes int) string {
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

func knowledgeJSON(value interface{}) string {
	payload, _ := json.Marshal(value)
	return string(payload)
}

func decodeKnowledgeTags(value string) []string {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	var tags []string
	if err := json.Unmarshal([]byte(value), &tags); err != nil {
		return nil
	}
	return normalizeKnowledgeTags(tags)
}

func knowledgeProjectFromModel(project models.KnowledgeProject, docCount int) knowledgeProjectResponse {
	return knowledgeProjectResponse{
		ID:            project.ID,
		UserID:        project.UserID,
		Name:          project.Name,
		Description:   project.Description,
		SortOrder:     project.SortOrder,
		DocumentCount: docCount,
		CreatedAt:     project.CreatedAt,
		UpdatedAt:     project.UpdatedAt,
	}
}

func knowledgeDocumentFromModel(document models.KnowledgeDocument) knowledgeDocumentResponse {
	return knowledgeDocumentResponse{
		ID:               document.ID,
		UserID:           document.UserID,
		ProjectID:        document.ProjectID,
		SourceDocumentID: document.SourceDocumentID,
		Type:             document.Type,
		Title:            document.Title,
		SourceName:       document.SourceName,
		Summary:          document.Summary,
		Tags:             decodeKnowledgeTags(document.TagsJSON),
		Content:          document.Content,
		CreatedAt:        document.CreatedAt,
		UpdatedAt:        document.UpdatedAt,
	}
}

func knowledgeDocumentResponses(documents []models.KnowledgeDocument, includeContent bool) []knowledgeDocumentResponse {
	responses := make([]knowledgeDocumentResponse, 0, len(documents))
	for _, document := range documents {
		resp := knowledgeDocumentFromModel(document)
		if !includeContent {
			resp.Content = ""
		}
		responses = append(responses, resp)
	}
	return responses
}

func knowledgeLinkFromModel(link models.KnowledgeLink) knowledgeLinkResponse {
	return knowledgeLinkResponse{
		ID:             link.ID,
		UserID:         link.UserID,
		ProjectID:      link.ProjectID,
		FromDocumentID: link.FromDocumentID,
		ToDocumentID:   link.ToDocumentID,
		Relation:       link.Relation,
		Explanation:    link.Explanation,
		Confidence:     link.Confidence,
		CreatedAt:      link.CreatedAt,
		UpdatedAt:      link.UpdatedAt,
	}
}

func knowledgeLinkResponses(links []models.KnowledgeLink) []knowledgeLinkResponse {
	responses := make([]knowledgeLinkResponse, 0, len(links))
	for _, link := range links {
		responses = append(responses, knowledgeLinkFromModel(link))
	}
	return responses
}

package handlers

import (
	"encoding/json"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

var (
	otaVersionPattern = regexp.MustCompile(`^[0-9A-Za-z][0-9A-Za-z._-]{0,79}$`)
	otaSHA256Pattern  = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

type otaManifestEntry struct {
	FileName    string `json:"file_name"`
	FileHash    string `json:"file_hash"`
	DownloadURL string `json:"download_url"`
}

type otaRelease struct {
	Version              string             `json:"version"`
	Sequence             int                `json:"sequence"`
	MinNativeVersionCode int                `json:"min_native_version_code"`
	MaxNativeVersionCode int                `json:"max_native_version_code"`
	PublishedAt          string             `json:"published_at,omitempty"`
	Manifest             []otaManifestEntry `json:"manifest"`
}

type AppVersionHandler struct {
	otaDir string
}

func NewAppVersionHandler(projectRoot string) *AppVersionHandler {
	otaDir := strings.TrimSpace(os.Getenv("AGENT_ASSISTANT_ANDROID_OTA_DIR"))
	if otaDir == "" {
		otaDir = filepath.Join(projectRoot, "artifacts", "android-ota")
	} else if !filepath.IsAbs(otaDir) {
		otaDir = filepath.Join(projectRoot, otaDir)
	}
	return &AppVersionHandler{otaDir: filepath.Clean(otaDir)}
}

func appVersionEnv(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func appVersionIntEnv(key string, fallback int) int {
	value, err := strconv.Atoi(appVersionEnv(key, strconv.Itoa(fallback)))
	if err != nil || value < 0 {
		return fallback
	}
	return value
}

func appVersionInt64Env(key string, fallback int64) int64 {
	value, err := strconv.ParseInt(appVersionEnv(key, strconv.FormatInt(fallback, 10)), 10, 64)
	if err != nil || value < 0 {
		return fallback
	}
	return value
}

func appVersionSHA256Env(key string) string {
	value := strings.ToLower(appVersionEnv(key, ""))
	if !otaSHA256Pattern.MatchString(value) {
		return ""
	}
	return value
}

func validOTAFileName(name string) bool {
	if name == "" || strings.HasPrefix(name, "/") || strings.Contains(name, "\\") {
		return false
	}
	cleaned := filepath.ToSlash(filepath.Clean(name))
	return cleaned == name && cleaned != "." && !strings.HasPrefix(cleaned, "../")
}

func (h *AppVersionHandler) latestOTA() *otaRelease {
	data, err := os.ReadFile(filepath.Join(h.otaDir, "latest.json"))
	if err != nil {
		return nil
	}
	var release otaRelease
	if err := json.Unmarshal(data, &release); err != nil {
		return nil
	}
	if !otaVersionPattern.MatchString(release.Version) || release.Sequence <= 0 || release.MinNativeVersionCode <= 0 {
		return nil
	}
	if release.MaxNativeVersionCode > 0 && release.MaxNativeVersionCode < release.MinNativeVersionCode {
		return nil
	}
	if len(release.Manifest) == 0 || len(release.Manifest) > 10000 {
		return nil
	}
	hasIndex := false
	for _, entry := range release.Manifest {
		if !validOTAFileName(entry.FileName) || !otaSHA256Pattern.MatchString(entry.FileHash) {
			return nil
		}
		if entry.DownloadURL == "" {
			return nil
		}
		if entry.FileName == "index.html" {
			hasIndex = true
		}
	}
	if !hasIndex {
		return nil
	}
	return &release
}

func (h *AppVersionHandler) Version(c *gin.Context) {
	latestCode := appVersionIntEnv("AGENT_ASSISTANT_ANDROID_LATEST_VERSION_CODE", 1)
	minCode := appVersionIntEnv("AGENT_ASSISTANT_ANDROID_MIN_VERSION_CODE", 1)
	if minCode > latestCode {
		minCode = latestCode
	}

	android := gin.H{
		"latest_version_code": latestCode,
		"latest_version_name": appVersionEnv("AGENT_ASSISTANT_ANDROID_LATEST_VERSION_NAME", "0.1.0"),
		"min_version_code":    minCode,
		"apk_url":             appVersionEnv("AGENT_ASSISTANT_ANDROID_APK_URL", ""),
		"apk_sha256":          appVersionSHA256Env("AGENT_ASSISTANT_ANDROID_APK_SHA256"),
		"apk_size":            appVersionInt64Env("AGENT_ASSISTANT_ANDROID_APK_SIZE", 0),
		"package_name":        appVersionEnv("AGENT_ASSISTANT_ANDROID_PACKAGE_NAME", "com.aan.agentassistant"),
		"release_notes":       appVersionEnv("AGENT_ASSISTANT_ANDROID_RELEASE_NOTES", ""),
	}
	if ota := h.latestOTA(); ota != nil {
		android["ota"] = ota
	}

	c.JSON(http.StatusOK, gin.H{
		"web_version": appVersionEnv("AGENT_ASSISTANT_WEB_VERSION", "dev"),
		"android":     android,
	})
}

func (h *AppVersionHandler) OTAFile(c *gin.Context) {
	version := c.Param("version")
	fileName := strings.TrimPrefix(c.Param("filepath"), "/")
	if !otaVersionPattern.MatchString(version) || !validOTAFileName(fileName) {
		c.Status(http.StatusNotFound)
		return
	}
	baseDir := filepath.Join(h.otaDir, version, "files")
	target := filepath.Join(baseDir, filepath.FromSlash(fileName))
	realBaseDir, err := filepath.EvalSymlinks(baseDir)
	if err != nil {
		c.Status(http.StatusNotFound)
		return
	}
	realTarget, err := filepath.EvalSymlinks(target)
	if err != nil {
		c.Status(http.StatusNotFound)
		return
	}
	relativePath, err := filepath.Rel(realBaseDir, realTarget)
	if err != nil || relativePath == ".." || strings.HasPrefix(relativePath, ".."+string(filepath.Separator)) {
		c.Status(http.StatusNotFound)
		return
	}
	info, err := os.Stat(realTarget)
	if err != nil || !info.Mode().IsRegular() {
		c.Status(http.StatusNotFound)
		return
	}
	c.Header("Cache-Control", "public, max-age=31536000, immutable")
	contentType := mime.TypeByExtension(filepath.Ext(realTarget))
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	c.Header("Content-Type", contentType)
	file, err := os.Open(realTarget)
	if err != nil {
		c.Status(http.StatusNotFound)
		return
	}
	defer file.Close()
	http.ServeContent(c.Writer, c.Request, "ota-asset", info.ModTime(), file)
}

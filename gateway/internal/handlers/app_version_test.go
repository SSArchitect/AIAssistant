package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestAppVersionDefaults(t *testing.T) {
	gin.SetMode(gin.TestMode)
	t.Setenv("AGENT_ASSISTANT_ANDROID_LATEST_VERSION_CODE", "")
	t.Setenv("AGENT_ASSISTANT_ANDROID_MIN_VERSION_CODE", "")

	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	context.Request = httptest.NewRequest(http.MethodGet, "/api/app/version", nil)
	NewAppVersionHandler(t.TempDir()).Version(context)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", recorder.Code)
	}
	var payload struct {
		WebVersion string `json:"web_version"`
		Android    struct {
			LatestVersionCode int `json:"latest_version_code"`
			MinVersionCode    int `json:"min_version_code"`
		} `json:"android"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload.WebVersion != "dev" || payload.Android.LatestVersionCode != 1 || payload.Android.MinVersionCode != 1 {
		t.Fatalf("unexpected defaults: %#v", payload)
	}
}

func TestAppVersionUsesReleaseEnvironment(t *testing.T) {
	gin.SetMode(gin.TestMode)
	t.Setenv("AGENT_ASSISTANT_WEB_VERSION", "2026.08.18.2")
	t.Setenv("AGENT_ASSISTANT_ANDROID_LATEST_VERSION_CODE", "8")
	t.Setenv("AGENT_ASSISTANT_ANDROID_MIN_VERSION_CODE", "9")
	t.Setenv("AGENT_ASSISTANT_ANDROID_LATEST_VERSION_NAME", "0.8.0")
	t.Setenv("AGENT_ASSISTANT_ANDROID_APK_URL", "https://example.com/app.apk")
	t.Setenv("AGENT_ASSISTANT_ANDROID_APK_SHA256", strings.Repeat("A", 64))
	t.Setenv("AGENT_ASSISTANT_ANDROID_APK_SIZE", "12345678")
	t.Setenv("AGENT_ASSISTANT_ANDROID_PACKAGE_NAME", "com.aan.agentassistant")

	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	context.Request = httptest.NewRequest(http.MethodGet, "/api/app/version", nil)
	NewAppVersionHandler(t.TempDir()).Version(context)

	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	android := payload["android"].(map[string]any)
	if android["latest_version_code"] != float64(8) || android["min_version_code"] != float64(8) {
		t.Fatalf("unexpected android release: %#v", android)
	}
	if android["apk_url"] != "https://example.com/app.apk" {
		t.Fatalf("unexpected apk url: %#v", android["apk_url"])
	}
	if android["apk_sha256"] != strings.Repeat("a", 64) || android["apk_size"] != float64(12345678) {
		t.Fatalf("unexpected APK verification metadata: %#v", android)
	}
	if android["package_name"] != "com.aan.agentassistant" {
		t.Fatalf("unexpected package name: %#v", android["package_name"])
	}
}

func TestAppVersionRejectsInvalidAPKMetadata(t *testing.T) {
	gin.SetMode(gin.TestMode)
	t.Setenv("AGENT_ASSISTANT_ANDROID_APK_SHA256", "not-a-sha256")
	t.Setenv("AGENT_ASSISTANT_ANDROID_APK_SIZE", "not-a-size")

	recorder := httptest.NewRecorder()
	context, _ := gin.CreateTestContext(recorder)
	context.Request = httptest.NewRequest(http.MethodGet, "/api/app/version", nil)
	NewAppVersionHandler(t.TempDir()).Version(context)

	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	android := payload["android"].(map[string]any)
	if android["apk_sha256"] != "" || android["apk_size"] != float64(0) {
		t.Fatalf("invalid APK metadata should be omitted safely: %#v", android)
	}
}

func TestAppVersionPublishesAndServesOTARelease(t *testing.T) {
	gin.SetMode(gin.TestMode)
	root := t.TempDir()
	otaDir := filepath.Join(root, "artifacts", "android-ota")
	filesDir := filepath.Join(otaDir, "0.1.0-ota.1", "files")
	if err := os.MkdirAll(filesDir, 0o755); err != nil {
		t.Fatalf("create OTA files: %v", err)
	}
	if err := os.WriteFile(filepath.Join(filesDir, "index.html"), []byte("ota-ready"), 0o644); err != nil {
		t.Fatalf("write OTA file: %v", err)
	}
	latest := `{
		"version":"0.1.0-ota.1",
		"sequence":1,
		"min_native_version_code":1,
		"max_native_version_code":1,
		"manifest":[{
			"file_name":"index.html",
			"file_hash":"` + strings.Repeat("a", 64) + `",
			"download_url":"/updates/android/0.1.0-ota.1/files/index.html"
		}]
	}`
	if err := os.WriteFile(filepath.Join(otaDir, "latest.json"), []byte(latest), 0o644); err != nil {
		t.Fatalf("write latest release: %v", err)
	}

	handler := NewAppVersionHandler(root)
	router := gin.New()
	router.GET("/api/app/version", handler.Version)
	router.GET("/updates/android/:version/files/*filepath", handler.OTAFile)

	versionRecorder := httptest.NewRecorder()
	router.ServeHTTP(versionRecorder, httptest.NewRequest(http.MethodGet, "/api/app/version", nil))
	if versionRecorder.Code != http.StatusOK || !strings.Contains(versionRecorder.Body.String(), `"sequence":1`) {
		t.Fatalf("unexpected OTA version response: %d %s", versionRecorder.Code, versionRecorder.Body.String())
	}

	fileRecorder := httptest.NewRecorder()
	router.ServeHTTP(fileRecorder, httptest.NewRequest(http.MethodGet, "/updates/android/0.1.0-ota.1/files/index.html", nil))
	if fileRecorder.Code != http.StatusOK || fileRecorder.Body.String() != "ota-ready" {
		t.Fatalf("unexpected OTA file response: %d %q", fileRecorder.Code, fileRecorder.Body.String())
	}
	if fileRecorder.Header().Get("Cache-Control") != "public, max-age=31536000, immutable" {
		t.Fatalf("unexpected cache policy: %q", fileRecorder.Header().Get("Cache-Control"))
	}
}

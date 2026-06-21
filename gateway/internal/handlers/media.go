package handlers

import (
	"context"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/url"
	"path"
	"regexp"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

const mediaDownloadMaxBytes int64 = 30 << 20

type MediaHandler struct {
	client *http.Client
}

func NewMediaHandler() *MediaHandler {
	return &MediaHandler{
		client: &http.Client{
			Timeout:   45 * time.Second,
			Transport: mediaDownloadTransport(),
		},
	}
}

func (h *MediaHandler) Download(c *gin.Context) {
	rawURL := strings.TrimSpace(c.Query("url"))
	if rawURL == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing url"})
		return
	}

	parsed, err := url.Parse(rawURL)
	if err != nil || parsed.Hostname() == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid image url"})
		return
	}

	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodGet, parsed.String(), nil)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid image request"})
		return
	}
	req.Header.Set("User-Agent", "AgentAssistantImageDownloader/1.0")
	req.Header.Set("Accept", "image/avif,image/webp,image/png,image/jpeg,image/gif,image/bmp,image/svg+xml;q=0.9,*/*;q=0.5")

	resp, err := h.client.Do(req)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "failed to fetch image"})
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		c.JSON(http.StatusBadGateway, gin.H{"error": fmt.Sprintf("image returned status %d", resp.StatusCode)})
		return
	}

	contentType := strings.TrimSpace(resp.Header.Get("Content-Type"))
	mediaType := mediaTypeOnly(contentType)
	if mediaType == "" {
		mediaType = imageMediaTypeFromPath(parsed.Path)
	}
	if mediaType == "" || !strings.HasPrefix(mediaType, "image/") {
		c.JSON(http.StatusUnsupportedMediaType, gin.H{"error": "url did not return an image"})
		return
	}
	if resp.ContentLength > mediaDownloadMaxBytes {
		c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "image is too large"})
		return
	}

	filename := mediaDownloadFilename(c.Query("filename"), parsed.Path, mediaType)
	c.Header("Content-Type", mediaType)
	c.Header("Content-Disposition", mime.FormatMediaType("attachment", map[string]string{"filename": filename}))
	c.Header("X-Content-Type-Options", "nosniff")

	_, _ = io.Copy(c.Writer, resp.Body)
}

func mediaDownloadTransport() *http.Transport {
	dialer := &net.Dialer{Timeout: 12 * time.Second, KeepAlive: 30 * time.Second}
	return &http.Transport{
		Proxy: nil,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			host, port, err := net.SplitHostPort(address)
			if err != nil {
				return nil, err
			}
			ips, err := net.DefaultResolver.LookupIPAddr(ctx, host)
			if err != nil {
				return nil, err
			}
			for _, candidate := range ips {
				if blockedMediaDownloadIP(candidate.IP) {
					continue
				}
				return dialer.DialContext(ctx, network, net.JoinHostPort(candidate.IP.String(), port))
			}
			return nil, errors.New("no public address for image host")
		},
	}
}

func blockedMediaDownloadIP(ip net.IP) bool {
	return ip == nil ||
		ip.IsUnspecified() ||
		ip.IsLoopback() ||
		ip.IsPrivate() ||
		ip.IsLinkLocalUnicast() ||
		ip.IsLinkLocalMulticast() ||
		ip.IsMulticast()
}

func mediaTypeOnly(contentType string) string {
	if contentType == "" {
		return ""
	}
	mediaType, _, err := mime.ParseMediaType(contentType)
	if err != nil {
		return ""
	}
	return strings.ToLower(mediaType)
}

func imageMediaTypeFromPath(value string) string {
	switch strings.ToLower(path.Ext(value)) {
	case ".png":
		return "image/png"
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".gif":
		return "image/gif"
	case ".webp":
		return "image/webp"
	case ".avif":
		return "image/avif"
	case ".bmp":
		return "image/bmp"
	case ".svg":
		return "image/svg+xml"
	default:
		return ""
	}
}

func mediaDownloadFilename(requested string, sourcePath string, mediaType string) string {
	filename := sanitizeMediaFilename(requested)
	if filename == "" {
		filename = sanitizeMediaFilename(path.Base(sourcePath))
	}
	if filename == "" || filename == "." || filename == "/" {
		filename = "superchat-image"
	}
	if path.Ext(filename) == "" {
		filename += mediaExtension(mediaType)
	}
	return filename
}

func mediaExtension(mediaType string) string {
	switch mediaType {
	case "image/jpeg":
		return ".jpg"
	case "image/png":
		return ".png"
	case "image/gif":
		return ".gif"
	case "image/webp":
		return ".webp"
	case "image/avif":
		return ".avif"
	case "image/bmp":
		return ".bmp"
	case "image/svg+xml":
		return ".svg"
	default:
		return ".png"
	}
}

var unsafeMediaFilenameChars = regexp.MustCompile(`[\\/:*?"<>|]+`)

func sanitizeMediaFilename(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	value = unsafeMediaFilenameChars.ReplaceAllString(value, "-")
	value = strings.Trim(value, ".- ")
	if len([]rune(value)) > 120 {
		runes := []rune(value)
		value = string(runes[:120])
	}
	return value
}

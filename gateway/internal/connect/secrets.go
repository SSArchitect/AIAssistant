package connect

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

func LoadKey(path string) ([]byte, error) {
	if key, err := os.ReadFile(path); err == nil {
		if len(key) != 32 {
			return nil, fmt.Errorf("invalid Connect encryption key")
		}
		return key, nil
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if os.IsExist(err) {
		return LoadKey(path)
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()
	if _, err = f.Write(key); err != nil {
		return nil, err
	}
	if err = f.Sync(); err != nil {
		return nil, err
	}
	return key, nil
}
func newCipher(key []byte) (cipher.AEAD, error) {
	b, e := aes.NewCipher(key)
	if e != nil {
		return nil, e
	}
	return cipher.NewGCM(b)
}
func (s *Service) seal(id string, c Config) (string, error) {
	b, e := json.Marshal(c)
	if e != nil {
		return "", e
	}
	nonce := make([]byte, s.cipher.NonceSize())
	if _, e = rand.Read(nonce); e != nil {
		return "", e
	}
	return base64.StdEncoding.EncodeToString(s.cipher.Seal(nonce, nonce, b, []byte(id))), nil
}
func (s *Service) open(id, value string) (Config, error) {
	raw, e := base64.StdEncoding.DecodeString(value)
	if e != nil || len(raw) < s.cipher.NonceSize() {
		return nil, fmt.Errorf("credentials unavailable")
	}
	n := s.cipher.NonceSize()
	b, e := s.cipher.Open(nil, raw[:n], raw[n:], []byte(id))
	if e != nil {
		return nil, fmt.Errorf("credentials unavailable")
	}
	var c Config
	e = json.Unmarshal(b, &c)
	return c, e
}

# Android APK 与增量 OTA 发布 Runbook

最后验证：2026-08-22

本文记录 Agent Assistant 安卓内测版在当前生产服务器上的发布、验证、回退和排障流程。
Android 容器的实现原理和本地开发说明见 [android-app.md](./android-app.md)，通用后端部署见
[server-deployment-runbook.md](./server-deployment-runbook.md)。

## 1. 当前生产基线

```text
Server:              ubuntu@49.235.143.82
Public URL:          https://www.architect8.cn
Server project:      /home/ubuntu/agent_assistant
APK download dir:    /var/www/agent-assistant-downloads
OTA root:            /home/ubuntu/agent_assistant/artifacts/android-ota
Nginx config:        /etc/nginx/conf.d/agent_assistant.conf
Gateway release env: /etc/systemd/system/agent-assistant-gateway.service.d/android-release.conf
TLS certificate:     /etc/letsencrypt/live/architect8.cn/fullchain.pem
TLS private key:     /etc/letsencrypt/live/architect8.cn/privkey.pem
```

已验证的版本基线：

```text
Native versionName:  0.3.0
Native versionCode:  3
OTA version:         0.3.0-ota.1
OTA sequence:        3
OTA native range:    versionCode >= 3
APK URL:             https://www.architect8.cn/downloads/agent-assistant-0.3.0-debug.apk
```

生产流量拓扑：

```text
Android / Browser
  -> HTTPS www.architect8.cn:443
      -> Nginx
          -> Go Gateway 127.0.0.1:8080
              -> Python Agent 127.0.0.1:9090
```

80 端口只负责跳转 HTTPS。Gateway 和 Agent 必须只监听 `127.0.0.1`，不能让公网绕过
Nginx 和 TLS 直接访问 8080/9090。

## 2. 先判断应该发什么

| 改动 | 发布方式 | 用户动作 |
| --- | --- | --- |
| HTML、CSS、JavaScript、手机布局 | 增量 OTA | App 内点击“立即应用” |
| Java/Kotlin、Capacitor 插件、权限、图标、Manifest | 新 APK | 下载并覆盖安装 |
| Gateway 或 Agent 后端 | 后端部署 | 通常无需更新 App |
| 同时涉及网页和原生能力 | 先发新 APK，再发限定原生版本的 OTA | 安装 APK 后应用 OTA |

OTA 不能更新原生代码。第一次使用 OTA 前，设备必须先安装包含更新器的 APK。

## 3. 发布规则

每次发布都遵守以下规则：

1. OTA `version` 永不复用，`sequence` 只增不减。
2. 已发布的 OTA 版本目录不可覆盖，因为资源响应带一年 `immutable` 缓存。
3. 先上传并验证完整版本目录，最后再原子替换 `latest.json`。
4. APK 使用 `Cache-Control: no-store`；OTA 文件使用内容哈希和永久缓存。
5. 远程版本接口、APK 和 OTA 文件只允许 HTTPS，App 中不写服务器 IP。
6. 新 APK 的 `versionCode` 必须严格增加；`versionName`、`package.json` 和发布接口保持一致。
7. APK 签名密钥必须保持不变，否则 Android 无法覆盖安装。

## 4. 发布网页增量 OTA

### 4.1 发布前检查

查看当前线上版本：

```bash
curl -fsS https://www.architect8.cn/api/app/version | python3 -m json.tool
```

确认本地改动并执行测试：

```bash
git status --short
node --test tests/*_web.js
cd gateway && go test ./... && cd ..
```

### 4.2 生成不可变发布包

下面以第二个 OTA 为例。版本名必须新建，序号必须高于线上的 `1`：

```bash
AGENT_ASSISTANT_API_BASE=https://www.architect8.cn \
  npm run android:ota -- 0.1.0-ota.2 2
```

默认适配所有 `versionCode >= 1` 的 APK。OTA 依赖新原生能力时，要限制可用范围：

```bash
AGENT_ASSISTANT_API_BASE=https://www.architect8.cn \
AGENT_ASSISTANT_OTA_MIN_NATIVE_VERSION_CODE=2 \
AGENT_ASSISTANT_OTA_MAX_NATIVE_VERSION_CODE=0 \
  npm run android:ota -- 0.2.0-ota.1 3
```

`MAX_NATIVE_VERSION_CODE=0` 表示不设上限。构建脚本会生成：

```text
artifacts/android-ota/<version>/files/
artifacts/android-ota/<version>/manifest.json
artifacts/android-ota/latest.json
```

发布前确认 `latest.json` 中的域名、版本、序号和原生版本范围：

```bash
python3 -m json.tool artifacts/android-ota/latest.json | sed -n '1,100p'
```

### 4.3 上传顺序

先传版本目录，确认服务器上不存在同名版本，再发布指针。以下命令中的版本值应替换为
本次真实版本：

```bash
ota_version=0.1.0-ota.2

ssh ubuntu@49.235.143.82 "set -e
test ! -e /tmp/agent-assistant-ota-$ota_version
test ! -e /home/ubuntu/agent_assistant/artifacts/android-ota/$ota_version
"
scp -r "artifacts/android-ota/$ota_version" \
  "ubuntu@49.235.143.82:/tmp/agent-assistant-ota-$ota_version"
scp artifacts/android-ota/latest.json \
  ubuntu@49.235.143.82:/tmp/agent-assistant-ota-latest.json

ssh ubuntu@49.235.143.82 "set -e
ota_root=/home/ubuntu/agent_assistant/artifacts/android-ota
test ! -e \"\$ota_root/$ota_version\"
mv /tmp/agent-assistant-ota-$ota_version \"\$ota_root/$ota_version\"
install -m 0644 /tmp/agent-assistant-ota-latest.json \"\$ota_root/.latest.pending\"
mv \"\$ota_root/.latest.pending\" \"\$ota_root/latest.json\"
"
```

Gateway 每次检查版本时都会读取 `latest.json`，单独发布 OTA 不需要重启服务。

### 4.4 发布后验证

```bash
curl -fsS https://www.architect8.cn/api/app/version | python3 -m json.tool
curl -fsSI \
  https://www.architect8.cn/updates/android/0.1.0-ota.2/files/index.html |
  sed -n '1,12p'
```

预期结果：

- 版本接口返回新 `version`、新 `sequence` 和非空 `manifest`。
- OTA 文件返回 `200`。
- 响应含 `Cache-Control: public, max-age=31536000, immutable`。
- App 启动或回到前台后下载更新，并显示“立即应用”。

## 5. 发布新 APK

### 5.1 更新版本号

同时更新以下位置：

- `android/app/build.gradle`：真实 Android `versionCode` 和 `versionName`。
- `package.json`：运行时显示的版本名。
- 构建时的 `AGENT_ASSISTANT_ANDROID_VERSION_CODE`：注入网页运行时配置。

例如发布 `0.3.0`、`versionCode 3`，并把当前线上 OTA 序号写入新 APK，避免重复应用旧
OTA：

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT="$ANDROID_HOME"

AGENT_ASSISTANT_API_BASE=https://www.architect8.cn \
AGENT_ASSISTANT_ANDROID_VERSION_CODE=3 \
AGENT_ASSISTANT_OTA_SEQUENCE=3 \
  npm run android:apk
```

### 5.2 校验签名和摘要

```bash
"$ANDROID_HOME/build-tools/36.0.0/apksigner" verify --verbose --print-certs \
  android/app/build/outputs/apk/debug/app-debug.apk
openssl dgst -sha256 android/app/build/outputs/apk/debug/app-debug.apk
```

当前内测包使用 Android Debug 签名。必须安全备份构建机上的 `~/.android/debug.keystore`，
且不能提交到 Git。密钥丢失或换密钥后，已安装用户只能先卸载旧 App 再安装新包，本地
App 数据也会随卸载清除。若分发范围扩大，应改用专用、长期保存的 release keystore。

### 5.3 上传 APK

建议让文件名包含版本，避免把不同原生版本混淆：

```bash
cp android/app/build/outputs/apk/debug/app-debug.apk \
  artifacts/agent-assistant-0.3.0-debug.apk

scp artifacts/agent-assistant-0.3.0-debug.apk \
  ubuntu@49.235.143.82:/tmp/agent-assistant-0.3.0-debug.apk

ssh ubuntu@49.235.143.82 '
sudo install -o root -g root -m 0644 \
  /tmp/agent-assistant-0.3.0-debug.apk \
  /var/www/agent-assistant-downloads/agent-assistant-0.3.0-debug.apk
'
```

Nginx 当前为 APK 下载配置了专用 location。文件名变化时，同步增加或更新下载 location，
随后执行：

```bash
ssh ubuntu@49.235.143.82 '
sudo nginx -t && sudo systemctl reload nginx
'
```

### 5.4 更新原生版本发现配置

编辑服务器上的：

```text
/etc/systemd/system/agent-assistant-gateway.service.d/android-release.conf
```

内容示例：

```ini
[Service]
Environment="AGENT_ASSISTANT_ANDROID_LATEST_VERSION_CODE=3"
Environment="AGENT_ASSISTANT_ANDROID_LATEST_VERSION_NAME=0.3.0"
Environment="AGENT_ASSISTANT_ANDROID_MIN_VERSION_CODE=1"
Environment="AGENT_ASSISTANT_ANDROID_APK_URL=https://www.architect8.cn/downloads/agent-assistant-0.3.0-debug.apk"
Environment="AGENT_ASSISTANT_ANDROID_APK_SHA256=<64 位小写 SHA-256>"
Environment="AGENT_ASSISTANT_ANDROID_APK_SIZE=<APK 精确字节数>"
Environment="AGENT_ASSISTANT_ANDROID_PACKAGE_NAME=com.aan.agentassistant"
Environment="AGENT_ASSISTANT_ANDROID_RELEASE_NOTES=本次更新说明"
```

应用并验证：

```bash
ssh ubuntu@49.235.143.82 '
set -e
sudo systemctl daemon-reload
sudo systemctl restart agent-assistant-gateway.service
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS https://www.architect8.cn/api/app/version | python3 -m json.tool
'
```

0.2.0 及更早的 App 发现新版后，会显示提示并用系统浏览器打开 `apk_url`。从 0.3.0
开始，App 会直接下载 APK，显示进度，并在摘要、大小、包名、版本号和签名全部校验通过后
拉起系统安装器。首次使用需要在 Android 设置里允许此 App“安装未知应用”，每次安装仍
必须由用户在系统界面确认；普通 App 无法绕过这两个 Android 安全边界。

## 6. HTTPS 与证书运维

生产证书覆盖：

```text
architect8.cn
www.architect8.cn
```

证书由 Certbot/Let's Encrypt 管理。检查证书和自动续期：

```bash
ssh ubuntu@49.235.143.82 '
sudo certbot certificates
systemctl is-enabled snap.certbot.renew.timer
systemctl is-active snap.certbot.renew.timer
'
```

安全地演练续期：

```bash
ssh ubuntu@49.235.143.82 \
  'sudo certbot renew --dry-run --no-random-sleep-on-renew'
```

检查 HTTP 跳转和 HTTPS 健康状态：

```bash
curl -fsSI http://www.architect8.cn/api/health | sed -n '1,8p'
curl -fsS https://www.architect8.cn/api/health
```

App 必须连接域名，不能连接 `https://49.235.143.82`，因为证书校验的是域名而不是 IP。
不要为排障重新开启 `usesCleartextTraffic`、混合内容或 HTTP OTA。

## 7. 回退与止损

### OTA 加载失败

如果新资源无法完成初始化，更新器会因为没有及时收到 `notifyAppReady()` 自动切回最近
一次成功版本，并记录该故障版本，避免同一设备循环安装。

### OTA 业务逻辑有误

如果页面能正常初始化，但业务行为有误，自动回退无法识别。处理顺序：

1. 把服务器的 `latest.json` 移到备份目录，停止新设备发现该版本。
2. 修复代码并发布全新的 OTA 版本和更高序号。
3. 不要重新覆盖故障版本目录，也不要把序号降回旧值。

停止发布指针时使用可恢复的移动操作：

```bash
ssh ubuntu@49.235.143.82 '
ota_root=/home/ubuntu/agent_assistant/artifacts/android-ota
backup_root=/home/ubuntu/backups/android-ota
sudo install -d -o ubuntu -g ubuntu -m 0755 "$backup_root"
mv "$ota_root/latest.json" \
  "$backup_root/latest-emergency-$(date +%Y%m%d-%H%M%S).json"
'
```

已经下载并被用户点击应用的业务缺陷版本，应尽快用更高序号的修复版覆盖其发现入口。

### APK 有问题

在版本发现配置中恢复上一稳定 APK 的元数据，并重启 Gateway。已经安装的新 APK 无法
通过 OTA 降级原生代码；必要时要发布更高 `versionCode` 的修复 APK。

## 8. 生产检查清单

```bash
ssh ubuntu@49.235.143.82 '
set -e
sudo nginx -t
systemctl is-active nginx \
  agent-assistant-gateway.service \
  agent-assistant-agent.service \
  snap.certbot.renew.timer
sudo ss -lnt | grep -E "127.0.0.1:(8080|9090)"
curl -fsS https://www.architect8.cn/api/health
curl -fsS https://www.architect8.cn/api/app/version | python3 -m json.tool
'
```

APK 下载应为 `200`、`no-store`：

```bash
curl -fsSI \
  https://www.architect8.cn/downloads/agent-assistant-0.3.0-debug.apk |
  sed -n '1,14p'
```

最后用一台真实 Android 设备完成：全新安装、登录、网盘列表/详情切换、版本发现、OTA
下载、立即应用、原生 APK 下载进度、安装权限、系统安装确认、重启后版本保持。服务端
接口成功不等于移动端完整链路一定成功。

## 9. 已踩过的坑

- `android.captureInput` 必须保持为 `false`。开启后 Capacitor 会用
  `BaseInputConnection` 替换 WebView 标准输入连接，豆包等整段提交文本的语音输入法可能
  通过 `ACTION_MULTIPLE` 被重复追加。这个配置属于原生 APK，不能依靠 Web OTA 修复。
- 原生 APK 更新必须同时发布 `APK_SHA256`、`APK_SIZE` 和 `PACKAGE_NAME`。元数据缺失时
  0.3.0 及以上版本会拒绝 App 内安装，并提供浏览器下载作为兼容入口。
- macOS 启用 VPN/TUN 后，SSH 或公网探测可能被错误路由；可临时使用
  `ssh -o BindInterface=en0 ...` 指定真实网卡，不要因此关闭服务器 TLS 校验。
- Android 模拟器 DNS 可能被宿主机代理改写。最终验收优先使用真实手机和真实公网。
- OTA 文件的 `HEAD` 路由必须和 `GET` 一样可用；下载器或探针可能先发 `HEAD`。
- CORS 必须允许 `X-Account-Session`、`X-User-ID`、`X-Account-ID`。
- `CapacitorUpdater.statsUrl` 当前设置为空，避免向第三方发送更新统计；重新生成 Android
  工程配置时要保留该设置。
- Certbot dry-run 默认可能随机等待；人工验证时使用
  `--no-random-sleep-on-renew`，自动定时任务保持默认即可。
- `artifacts/` 被 Git 忽略。OTA 和 APK 是发布产物，不能依赖 Git pull 自动出现在服务器。

## 10. 备份位置

2026-08-19 首次上线 HTTPS/OTA 时的服务器备份：

```text
/home/ubuntu/backups/nginx-agent-assistant-pre-https-20260819.conf
/home/ubuntu/backups/nginx-agent-assistant-https-certbot-20260819.conf
/home/ubuntu/backups/agent-assistant-20260819/
```

2026-08-22 发布 0.3.0 前的就地回滚文件后缀为 `.bak.0.2.0-to-0.3.0`，分别保存在当前
Gateway 二进制、`app_version.go`、Nginx 配置和版本环境文件旁边。

备份中不应记录或复制证书私钥、模型 API key、数据库明文内容。证书私钥由 Certbot 在
`/etc/letsencrypt` 下管理，运行期帐号和模型配置仍以服务器数据库为准。

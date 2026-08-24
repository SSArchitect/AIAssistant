# Android App

当前 Android 版本使用 Capacitor 8，复用 `web/` 中的移动端页面，应用包名为
`com.aan.agentassistant`，最低支持 Android 7（API 24）。

本文侧重实现原理和本地构建。生产服务器路径、HTTPS 证书、APK/OTA 发布、回退和排障
步骤见 [android-release-runbook.md](./android-release-runbook.md)。

## 构建 Debug APK

需要 Node.js 22+、JDK 21 和 Android SDK 36。macOS + Homebrew 环境可以使用：

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export ANDROID_SDK_ROOT="$ANDROID_HOME"

npm install
npm run android:apk
```

APK 输出到：

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

## 配置服务端

构建脚本默认连接正式服务 `https://www.architect8.cn`。可以在构建时覆盖：

```bash
AGENT_ASSISTANT_API_BASE=https://www.architect8.cn npm run android:apk
```

`scripts/build_android_web.mjs` 会把网页复制到 `dist/android-web/`，并只在复制后的
Android 资源里注入服务地址，不会改变网页端的同源 API 行为。

## 内测限制

- Android 生产配置只允许 HTTPS，已关闭混合内容、明文服务和 Manifest 明文流量。
- Debug APK 使用 Android 默认调试证书，只适合本地安装；应用商店需要单独创建并妥善保存
  release keystore，再生成签名 AAB。
- Android 跨域调用使用 `X-Account-Session`、`X-User-ID` 等请求头；当前网页请求仍保留
  查询参数兼容路径。Gateway 的 CORS 配置已允许这些自定义请求头。
- 已支持系统返回键、外链浏览器、系统分享桥接和 App 内 APK 下载更新，暂未接入推送
  通知与深链。

## 原生版本检测

Android 容器启动及回到前台时会请求 `GET /api/app/version`，一小时内最多
检查一次。出于防止更新地址被劫持的考虑，非本地服务只会通过 HTTPS 检查版本。
服务端可以用以下环境变量发布新版：

```bash
AGENT_ASSISTANT_WEB_VERSION=2026.08.18.2
AGENT_ASSISTANT_ANDROID_LATEST_VERSION_CODE=3
AGENT_ASSISTANT_ANDROID_LATEST_VERSION_NAME=0.3.0
AGENT_ASSISTANT_ANDROID_MIN_VERSION_CODE=1
AGENT_ASSISTANT_ANDROID_APK_URL=https://www.architect8.cn/downloads/agent-assistant-0.3.0-debug.apk
AGENT_ASSISTANT_ANDROID_APK_SHA256='<APK 的 64 位小写 SHA-256>'
AGENT_ASSISTANT_ANDROID_APK_SIZE='<APK 精确字节数>'
AGENT_ASSISTANT_ANDROID_PACKAGE_NAME=com.aan.agentassistant
AGENT_ASSISTANT_ANDROID_RELEASE_NOTES='新增 App 内安全下载更新'
```

当 `LATEST_VERSION_CODE` 高于 App 内置版本时，App 底部会显示更新提示。0.3.0 及以上版本
在 App 内下载 APK、显示进度，并校验 HTTPS、精确大小、SHA-256、包名、版本号和当前 App
签名；全部通过后才拉起 Android 系统安装器。首次使用需要用户允许“安装未知应用”，每次
安装仍需要用户在系统界面确认。0.2.0 及更早版本仍通过浏览器下载 0.3.0。

原生 Java/Kotlin、Capacitor 插件、权限和图标等改动仍需发布新 APK；只有 `web/` 页面资源
适合走下面的 OTA。0.3.0 的内置更新器只是让后续 APK 升级不再跳转浏览器，并没有把原生
改动变成 OTA。

## Web 资源增量 OTA

当前 App 已集成手动 OTA 更新器。App 启动和回到前台时感知新版本，下载完成后显示
“立即应用”。每个文件都使用 SHA-256 校验；设备会复用 APK 内置资源和历史缓存中
哈希相同的文件，只下载真正变化的部分，不会再次下载整套网页。

新下载的资源切换后必须在 30 秒内完成 JavaScript 初始化并调用 `notifyAppReady()`。
如果入口脚本损坏或无法运行，更新器会自动切回最近一次成功版本、删除故障包并记住
故障版本，避免循环提示。历史成功包也会自动清理，不会无限占用存储。

这项能力需要先安装一次包含更新器的新版 APK。之后普通 HTML、CSS、JavaScript
改动才可以不重装 App；新增原生能力时仍要升级 APK。

### 1. 生成发布目录

版本名必须唯一，序号必须是严格递增的正整数。同一版本目录不可覆盖，因为资源接口
使用永久缓存：

```bash
AGENT_ASSISTANT_API_BASE=https://www.architect8.cn \
  npm run android:ota -- 0.1.0-ota.1 1
```

默认适配所有 `versionCode >= 1` 的 App。需要限制原生版本范围时使用：

```bash
AGENT_ASSISTANT_API_BASE=https://www.architect8.cn \
AGENT_ASSISTANT_OTA_MIN_NATIVE_VERSION_CODE=2 \
AGENT_ASSISTANT_OTA_MAX_NATIVE_VERSION_CODE=4 \
  npm run android:ota -- 0.2.0-ota.1 2
```

`MAX_NATIVE_VERSION_CODE=0` 表示不设上限。产物位于：

```text
artifacts/android-ota/
├── 0.1.0-ota.1/
│   ├── files/          # 完整网页文件；设备按哈希增量获取
│   └── manifest.json
└── latest.json         # 当前发布指针
```

### 2. 发布到 Gateway

Gateway 默认从项目下的 `artifacts/android-ota/` 读取，也可以指定独立目录：

```bash
AGENT_ASSISTANT_ANDROID_OTA_DIR=/srv/agent-assistant/android-ota
```

部署时先完整上传新版本目录，校验完成后最后原子替换 `latest.json`。不要先发布
`latest.json`，否则客户端可能在文件尚未齐全时开始下载。Gateway 不需要为每次 OTA
重启，会在每次版本检查时读取最新指针。

发布后可以先检查：

```bash
curl https://www.architect8.cn/api/app/version
curl -I https://www.architect8.cn/updates/android/0.1.0-ota.1/files/index.html
```

### 3. 回退与修复

- 某台设备加载失败时会自动回到上一成功版本。
- 如果业务逻辑有误但页面仍能初始化，自动机制无法判断它是坏版本。应从服务端撤下
  `latest.json`，再把已验证代码发布为一个新的唯一版本和更高序号。
- 不要降低序号或覆盖旧版本；客户端会拒绝降级，旧资源 URL 也可能已被永久缓存。

### 安全边界

远程版本发现和文件下载只接受 HTTPS；`localhost`、`127.0.0.1` 和安卓模拟器的
`10.0.2.2` 仅用于本地测试。SHA-256 可以发现文件损坏或与清单不一致，但清单身份
仍依赖 HTTPS。正式服务 `https://www.architect8.cn` 已配置有效证书并启用 OTA；若未来
面向不受控的公开分发，再增加独立的清单签名。

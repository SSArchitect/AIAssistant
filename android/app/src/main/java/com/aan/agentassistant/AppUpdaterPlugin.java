package com.aan.agentassistant;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

@CapacitorPlugin(name = "AppUpdater")
public class AppUpdaterPlugin extends Plugin {
    private static final int CONNECT_TIMEOUT_MS = 15_000;
    private static final int READ_TIMEOUT_MS = 30_000;
    private static final int MAX_REDIRECTS = 5;
    private static final long MAX_APK_SIZE = 512L * 1024L * 1024L;
    private static final String APK_MIME_TYPE = "application/vnd.android.package-archive";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean updateInProgress = new AtomicBoolean(false);

    @PluginMethod
    public void canInstallPackages(PluginCall call) {
        JSObject result = new JSObject();
        result.put("granted", canRequestPackageInstalls());
        call.resolve(result);
    }

    @PluginMethod
    public void openInstallPermission(PluginCall call) {
        if (canRequestPackageInstalls()) {
            JSObject result = new JSObject();
            result.put("granted", true);
            call.resolve(result);
            return;
        }

        Intent intent = new Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:" + getContext().getPackageName())
        );
        try {
            getActivity().startActivity(intent);
            JSObject result = new JSObject();
            result.put("opened", true);
            call.resolve(result);
        } catch (ActivityNotFoundException error) {
            call.reject("System install permission settings are unavailable.", "INSTALL_PERMISSION_UNAVAILABLE", error);
        }
    }

    @PluginMethod
    public void downloadAndInstall(PluginCall call) {
        String rawUrl = call.getString("url", "").trim();
        String expectedHash = call.getString("sha256", "").trim().toLowerCase(Locale.US);
        String expectedPackage = call.getString("packageName", getContext().getPackageName()).trim();
        Long expectedSizeValue = call.getLong("size", 0L);
        Long expectedVersionValue = call.getLong("versionCode", 0L);
        long expectedSize = expectedSizeValue == null ? 0L : expectedSizeValue;
        long expectedVersionCode = expectedVersionValue == null ? 0L : expectedVersionValue;

        if (!canRequestPackageInstalls()) {
            call.reject("Permission to install unknown apps is required.", "INSTALL_PERMISSION_REQUIRED");
            return;
        }
        if (!isSecureHttpsUrl(rawUrl)) {
            call.reject("The update URL must use HTTPS.", "INVALID_UPDATE");
            return;
        }
        if (!expectedHash.matches("^[0-9a-f]{64}$")) {
            call.reject("A valid APK SHA-256 digest is required.", "INVALID_UPDATE");
            return;
        }
        if (expectedSize <= 0 || expectedSize > MAX_APK_SIZE || expectedVersionCode <= 0) {
            call.reject("Invalid APK size or version.", "INVALID_UPDATE");
            return;
        }
        if (!getContext().getPackageName().equals(expectedPackage)) {
            call.reject("The update package does not match this app.", "INVALID_UPDATE");
            return;
        }
        if (!updateInProgress.compareAndSet(false, true)) {
            call.reject("An app update is already in progress.", "UPDATE_IN_PROGRESS");
            return;
        }

        executor.execute(() -> {
            File temporaryFile = null;
            try {
                long currentVersionCode = installedVersionCode();
                if (expectedVersionCode <= currentVersionCode) {
                    reject(call, "The APK is not newer than the installed app.", "APK_INVALID", null);
                    return;
                }

                File updateDirectory = new File(getContext().getFilesDir(), "updates");
                if (!updateDirectory.exists() && !updateDirectory.mkdirs()) {
                    throw new IOException("Unable to create the update directory.");
                }
                deleteDirectoryContents(updateDirectory);
                temporaryFile = new File(updateDirectory, "update-" + expectedVersionCode + ".apk.part");
                File verifiedFile = new File(updateDirectory, "update-" + expectedVersionCode + ".apk");

                String actualHash = download(rawUrl, temporaryFile, expectedSize);
                if (!expectedHash.equals(actualHash)) {
                    reject(call, "The downloaded APK checksum does not match.", "HASH_MISMATCH", null);
                    return;
                }
                if (!verifyApk(temporaryFile, expectedPackage, expectedVersionCode)) {
                    reject(call, "The downloaded APK failed package, version, or signature validation.", "APK_INVALID", null);
                    return;
                }
                if (!temporaryFile.renameTo(verifiedFile)) {
                    throw new IOException("Unable to finalize the downloaded APK.");
                }
                temporaryFile = null;
                launchInstaller(call, verifiedFile);
            } catch (DownloadException error) {
                reject(call, error.getMessage(), "DOWNLOAD_FAILED", error);
            } catch (Exception error) {
                reject(call, "Unable to prepare the app update.", "DOWNLOAD_FAILED", error);
            } finally {
                if (temporaryFile != null && temporaryFile.exists()) {
                    //noinspection ResultOfMethodCallIgnored
                    temporaryFile.delete();
                }
                updateInProgress.set(false);
            }
        });
    }

    private boolean canRequestPackageInstalls() {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.O || getContext().getPackageManager().canRequestPackageInstalls();
    }

    private boolean isSecureHttpsUrl(String rawUrl) {
        try {
            URI uri = URI.create(rawUrl);
            return "https".equalsIgnoreCase(uri.getScheme()) && uri.getHost() != null && !uri.getHost().isEmpty();
        } catch (IllegalArgumentException error) {
            return false;
        }
    }

    private String download(String rawUrl, File destination, long expectedSize) throws Exception {
        URL currentUrl = new URL(rawUrl);
        for (int redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount++) {
            HttpURLConnection connection = (HttpURLConnection) currentUrl.openConnection();
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("Accept", APK_MIME_TYPE);
            connection.setRequestProperty("Accept-Encoding", "identity");
            connection.connect();
            int responseCode = connection.getResponseCode();

            if (responseCode >= 300 && responseCode < 400) {
                String location = connection.getHeaderField("Location");
                connection.disconnect();
                if (location == null || location.trim().isEmpty() || redirectCount == MAX_REDIRECTS) {
                    throw new DownloadException("Invalid or excessive APK redirect.");
                }
                URL redirectedUrl = new URL(currentUrl, location);
                if (!isSecureHttpsUrl(redirectedUrl.toString())) {
                    throw new DownloadException("An APK redirect attempted to leave HTTPS.");
                }
                currentUrl = redirectedUrl;
                continue;
            }
            if (responseCode != HttpURLConnection.HTTP_OK) {
                connection.disconnect();
                throw new DownloadException("APK download returned HTTP " + responseCode + ".");
            }

            long contentLength = connection.getContentLengthLong();
            if (contentLength > 0 && contentLength != expectedSize) {
                connection.disconnect();
                throw new DownloadException("APK response size does not match the release metadata.");
            }

            try {
                MessageDigest digest = MessageDigest.getInstance("SHA-256");
                long received = 0;
                long lastProgressAt = 0;
                byte[] buffer = new byte[64 * 1024];
                try (
                    BufferedInputStream input = new BufferedInputStream(connection.getInputStream());
                    BufferedOutputStream output = new BufferedOutputStream(new FileOutputStream(destination))
                ) {
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        received += count;
                        if (received > expectedSize || received > MAX_APK_SIZE) {
                            throw new DownloadException("APK download exceeded the expected size.");
                        }
                        output.write(buffer, 0, count);
                        digest.update(buffer, 0, count);
                        long now = System.currentTimeMillis();
                        if (lastProgressAt == 0 || now - lastProgressAt >= 250 || received == expectedSize) {
                            emitProgress(received, expectedSize);
                            lastProgressAt = now;
                        }
                    }
                } finally {
                    connection.disconnect();
                }
                if (received != expectedSize) {
                    throw new DownloadException("APK download was incomplete.");
                }
                return toHex(digest.digest());
            } catch (NoSuchAlgorithmException error) {
                throw new IllegalStateException("SHA-256 is unavailable.", error);
            }
        }
        throw new DownloadException("Too many APK redirects.");
    }

    private boolean verifyApk(File apkFile, String expectedPackage, long expectedVersionCode) throws Exception {
        PackageManager packageManager = getContext().getPackageManager();
        int signatureFlags = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            ? PackageManager.GET_SIGNING_CERTIFICATES
            : PackageManager.GET_SIGNATURES;
        PackageInfo archiveInfo = packageManager.getPackageArchiveInfo(apkFile.getAbsolutePath(), signatureFlags);
        if (archiveInfo == null || !expectedPackage.equals(archiveInfo.packageName)) {
            return false;
        }
        long archiveVersionCode = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            ? archiveInfo.getLongVersionCode()
            : archiveInfo.versionCode;
        if (archiveVersionCode != expectedVersionCode) {
            return false;
        }
        PackageInfo installedInfo = packageManager.getPackageInfo(getContext().getPackageName(), signatureFlags);
        return signatureDigests(archiveInfo).equals(signatureDigests(installedInfo)) && !signatureDigests(installedInfo).isEmpty();
    }

    private long installedVersionCode() throws PackageManager.NameNotFoundException {
        PackageInfo packageInfo = getContext().getPackageManager().getPackageInfo(getContext().getPackageName(), 0);
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P ? packageInfo.getLongVersionCode() : packageInfo.versionCode;
    }

    @SuppressWarnings("deprecation")
    private Set<String> signatureDigests(PackageInfo packageInfo) throws NoSuchAlgorithmException {
        Signature[] signatures;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && packageInfo.signingInfo != null) {
            signatures = packageInfo.signingInfo.hasMultipleSigners()
                ? packageInfo.signingInfo.getApkContentsSigners()
                : packageInfo.signingInfo.getSigningCertificateHistory();
        } else {
            signatures = packageInfo.signatures;
        }
        Set<String> digests = new HashSet<>();
        if (signatures == null) {
            return digests;
        }
        for (Signature signature : signatures) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digests.add(toHex(digest.digest(signature.toByteArray())));
        }
        return digests;
    }

    private void launchInstaller(PluginCall call, File apkFile) {
        Uri apkUri = FileProvider.getUriForFile(
            getContext(),
            getContext().getPackageName() + ".fileprovider",
            apkFile
        );
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(apkUri, APK_MIME_TYPE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        getActivity().runOnUiThread(() -> {
            try {
                getActivity().startActivity(intent);
                JSObject result = new JSObject();
                result.put("installerOpened", true);
                call.resolve(result);
            } catch (ActivityNotFoundException error) {
                call.reject("No system package installer is available.", "INSTALLER_UNAVAILABLE", error);
            }
        });
    }

    private void emitProgress(long received, long total) {
        JSObject progress = new JSObject();
        progress.put("received", received);
        progress.put("total", total);
        progress.put("percent", Math.min(100, Math.round(received * 100.0 / total)));
        getActivity().runOnUiThread(() -> notifyListeners("downloadProgress", progress));
    }

    private void reject(PluginCall call, String message, String code, Exception error) {
        getActivity().runOnUiThread(() -> {
            if (error == null) {
                call.reject(message, code);
            } else {
                call.reject(message, code, error);
            }
        });
    }

    private void deleteDirectoryContents(File directory) {
        File[] files = directory.listFiles();
        if (files == null) {
            return;
        }
        for (File file : files) {
            if (file.isFile()) {
                //noinspection ResultOfMethodCallIgnored
                file.delete();
            }
        }
    }

    private String toHex(byte[] bytes) {
        StringBuilder value = new StringBuilder(bytes.length * 2);
        for (byte item : bytes) {
            value.append(String.format(Locale.US, "%02x", item & 0xff));
        }
        return value.toString();
    }

    @Override
    protected void handleOnDestroy() {
        executor.shutdownNow();
    }

    private static class DownloadException extends IOException {
        DownloadException(String message) {
            super(message);
        }
    }
}

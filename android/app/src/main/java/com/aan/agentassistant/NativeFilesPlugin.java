package com.aan.agentassistant;

import android.Manifest;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@CapacitorPlugin(
    name = "NativeFiles",
    permissions = {
        @Permission(
            alias = "legacyStorage",
            strings = { Manifest.permission.WRITE_EXTERNAL_STORAGE }
        )
    }
)
public class NativeFilesPlugin extends Plugin {
    private static final long MAX_FILE_SIZE = 64L * 1024L * 1024L;
    private static final String DEFAULT_MIME_TYPE = "application/octet-stream";
    private static final String DOWNLOAD_SUBDIRECTORY = "Agent Assistant";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    @PluginMethod
    public void copyImage(PluginCall call) {
        NativePayload payload;
        try {
            payload = nativePayload(call, true);
        } catch (IllegalArgumentException error) {
            call.reject(error.getMessage(), "INVALID_FILE", error);
            return;
        }

        executor.execute(() -> {
            try {
                File directory = new File(getContext().getCacheDir(), "clipboard-images");
                ensureDirectory(directory);
                deleteDirectoryContents(directory);
                File image = new File(directory, System.currentTimeMillis() + "-" + payload.filename);
                writeBytes(image, payload.bytes);
                Uri uri = FileProvider.getUriForFile(
                    getContext(),
                    getContext().getPackageName() + ".fileprovider",
                    image
                );
                getActivity().runOnUiThread(() -> copyImageUri(call, uri, payload));
            } catch (Exception error) {
                reject(call, "Unable to copy the image.", "COPY_FAILED", error);
            }
        });
    }

    @PluginMethod
    public void saveFile(PluginCall call) {
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P && getPermissionState("legacyStorage") != PermissionState.GRANTED) {
            requestPermissionForAlias("legacyStorage", call, "legacyStoragePermissionResult");
            return;
        }
        saveFileWithPermission(call);
    }

    @PermissionCallback
    private void legacyStoragePermissionResult(PluginCall call) {
        if (getPermissionState("legacyStorage") != PermissionState.GRANTED) {
            call.reject("Storage permission is required to save downloads on this Android version.", "STORAGE_PERMISSION_DENIED");
            return;
        }
        saveFileWithPermission(call);
    }

    private void saveFileWithPermission(PluginCall call) {
        NativePayload payload;
        try {
            payload = nativePayload(call, false);
        } catch (IllegalArgumentException error) {
            call.reject(error.getMessage(), "INVALID_FILE", error);
            return;
        }

        executor.execute(() -> {
            try {
                SavedFile saved = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                    ? saveWithMediaStore(payload)
                    : saveToLegacyDownloads(payload);
                resolveSavedFile(call, saved, payload);
            } catch (Exception error) {
                reject(call, "Unable to save the file to Downloads.", "SAVE_FAILED", error);
            }
        });
    }

    private NativePayload nativePayload(PluginCall call, boolean imageOnly) {
        String rawData = call.getString("data", "").trim();
        if (rawData.startsWith("data:")) {
            int comma = rawData.indexOf(',');
            if (comma < 0 || !rawData.substring(0, comma).toLowerCase(Locale.US).contains(";base64")) {
                throw new IllegalArgumentException("The file data must be base64 encoded.");
            }
            rawData = rawData.substring(comma + 1);
        }
        if (rawData.isEmpty() || rawData.length() > ((MAX_FILE_SIZE + 2L) / 3L) * 4L + 16L) {
            throw new IllegalArgumentException("The file is empty or exceeds the native transfer limit.");
        }

        byte[] bytes;
        try {
            bytes = Base64.decode(rawData, Base64.DEFAULT);
        } catch (IllegalArgumentException error) {
            throw new IllegalArgumentException("The file data is not valid base64.", error);
        }
        if (bytes.length == 0 || bytes.length > MAX_FILE_SIZE) {
            throw new IllegalArgumentException("The file is empty or exceeds the native transfer limit.");
        }

        String mimeType = safeMimeType(call.getString("mimeType", DEFAULT_MIME_TYPE));
        if (imageOnly && !mimeType.startsWith("image/")) {
            throw new IllegalArgumentException("Only images can be copied to the image clipboard.");
        }
        String fallback = imageOnly ? "image.png" : "download";
        return new NativePayload(bytes, safeFilename(call.getString("filename", fallback), fallback), mimeType);
    }

    private void copyImageUri(PluginCall call, Uri uri, NativePayload payload) {
        try {
            ClipboardManager clipboard = (ClipboardManager) getContext().getSystemService(Context.CLIPBOARD_SERVICE);
            if (clipboard == null) {
                call.reject("The system clipboard is unavailable.", "CLIPBOARD_UNAVAILABLE");
                return;
            }
            ClipData clip = ClipData.newUri(getContext().getContentResolver(), payload.filename, uri);
            clipboard.setPrimaryClip(clip);
            JSObject result = new JSObject();
            result.put("copied", true);
            result.put("mimeType", payload.mimeType);
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Unable to copy the image.", "COPY_FAILED", error);
        }
    }

    private SavedFile saveWithMediaStore(NativePayload payload) throws IOException {
        ContentResolver resolver = getContext().getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, payload.filename);
        values.put(MediaStore.MediaColumns.MIME_TYPE, payload.mimeType);
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/" + DOWNLOAD_SUBDIRECTORY);
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);

        Uri collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY);
        Uri uri = resolver.insert(collection, values);
        if (uri == null) throw new IOException("Unable to create a system download entry.");
        boolean completed = false;
        try {
            try (OutputStream output = resolver.openOutputStream(uri, "w")) {
                if (output == null) throw new IOException("Unable to open the system download entry.");
                output.write(payload.bytes);
                output.flush();
            }
            ContentValues complete = new ContentValues();
            complete.put(MediaStore.MediaColumns.IS_PENDING, 0);
            resolver.update(uri, complete, null, null);
            completed = true;
            return new SavedFile(uri.toString(), payload.filename);
        } finally {
            if (!completed) resolver.delete(uri, null, null);
        }
    }

    @SuppressWarnings("deprecation")
    private SavedFile saveToLegacyDownloads(NativePayload payload) throws IOException {
        File downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        File directory = new File(downloads, DOWNLOAD_SUBDIRECTORY);
        ensureDirectory(directory);
        File target = uniqueFile(directory, payload.filename);
        writeBytes(target, payload.bytes);
        MediaScannerConnection.scanFile(
            getContext(),
            new String[] { target.getAbsolutePath() },
            new String[] { payload.mimeType },
            null
        );
        return new SavedFile(Uri.fromFile(target).toString(), target.getName());
    }

    private void resolveSavedFile(PluginCall call, SavedFile saved, NativePayload payload) {
        getActivity().runOnUiThread(() -> {
            Toast.makeText(getContext(), "已保存到下载目录", Toast.LENGTH_SHORT).show();
            JSObject result = new JSObject();
            result.put("saved", true);
            result.put("filename", saved.filename);
            result.put("uri", saved.uri);
            result.put("mimeType", payload.mimeType);
            result.put("size", payload.bytes.length);
            call.resolve(result);
        });
    }

    static String safeFilename(String value, String fallback) {
        String normalized = value == null ? "" : value.trim();
        normalized = normalized.replaceAll("[\\x00-\\x1f\\x7f/\\\\:*?\"<>|]", "_");
        while (normalized.startsWith(".")) normalized = normalized.substring(1);
        normalized = normalized.trim();
        if (normalized.isEmpty()) normalized = fallback;
        if (normalized.length() > 120) normalized = normalized.substring(0, 120).trim();
        return normalized.isEmpty() ? fallback : normalized;
    }

    static String safeMimeType(String value) {
        String normalized = value == null ? "" : value.trim().toLowerCase(Locale.US);
        int separator = normalized.indexOf(';');
        if (separator >= 0) normalized = normalized.substring(0, separator).trim();
        return normalized.matches("^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
            ? normalized
            : DEFAULT_MIME_TYPE;
    }

    private static File uniqueFile(File directory, String filename) {
        File target = new File(directory, filename);
        if (!target.exists()) return target;
        int dot = filename.lastIndexOf('.');
        String stem = dot > 0 ? filename.substring(0, dot) : filename;
        String extension = dot > 0 ? filename.substring(dot) : "";
        for (int copy = 1; copy < 10000; copy++) {
            target = new File(directory, stem + " (" + copy + ")" + extension);
            if (!target.exists()) return target;
        }
        return new File(directory, System.currentTimeMillis() + "-" + filename);
    }

    private static void ensureDirectory(File directory) throws IOException {
        if (!directory.exists() && !directory.mkdirs()) {
            throw new IOException("Unable to create the destination directory.");
        }
        if (!directory.isDirectory()) throw new IOException("The destination is not a directory.");
    }

    private static void writeBytes(File target, byte[] bytes) throws IOException {
        try (FileOutputStream output = new FileOutputStream(target)) {
            output.write(bytes);
            output.flush();
        }
    }

    private static void deleteDirectoryContents(File directory) {
        File[] files = directory.listFiles();
        if (files == null) return;
        for (File file : files) {
            if (file.isFile()) {
                //noinspection ResultOfMethodCallIgnored
                file.delete();
            }
        }
    }

    private void reject(PluginCall call, String message, String code, Exception error) {
        getActivity().runOnUiThread(() -> call.reject(message, code, error));
    }

    @Override
    protected void handleOnDestroy() {
        executor.shutdownNow();
    }

    private static class NativePayload {
        final byte[] bytes;
        final String filename;
        final String mimeType;

        NativePayload(byte[] bytes, String filename, String mimeType) {
            this.bytes = bytes;
            this.filename = filename;
            this.mimeType = mimeType;
        }
    }

    private static class SavedFile {
        final String uri;
        final String filename;

        SavedFile(String uri, String filename) {
            this.uri = uri;
            this.filename = filename;
        }
    }
}

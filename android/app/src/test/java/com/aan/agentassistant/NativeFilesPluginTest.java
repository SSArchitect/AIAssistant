package com.aan.agentassistant;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class NativeFilesPluginTest {
    @Test
    public void safeFilenameRemovesPathAndControlCharacters() {
        assertEquals("_secret_report_.pdf", NativeFilesPlugin.safeFilename("../secret/report?.pdf", "download"));
        assertEquals("download", NativeFilesPlugin.safeFilename("...", "download"));
    }

    @Test
    public void safeMimeTypeAcceptsMediaTypesAndRejectsInvalidValues() {
        assertEquals("image/png", NativeFilesPlugin.safeMimeType("Image/PNG; charset=binary"));
        assertEquals("application/octet-stream", NativeFilesPlugin.safeMimeType("not a mime type"));
    }
}

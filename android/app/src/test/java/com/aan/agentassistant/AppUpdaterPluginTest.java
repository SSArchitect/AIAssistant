package com.aan.agentassistant;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class AppUpdaterPluginTest {
    @Test
    public void acceptsOrdinaryJsonIntegersForApkSizeAndVersion() {
        assertEquals(7819006L, AppUpdaterPlugin.positiveUpdateInteger(Integer.valueOf(7819006)));
        assertEquals(5L, AppUpdaterPlugin.positiveUpdateInteger(Integer.valueOf(5)));
    }

    @Test
    public void acceptsOtherExactBridgeNumberRepresentations() {
        assertEquals(7819006L, AppUpdaterPlugin.positiveUpdateInteger(Long.valueOf(7819006)));
        assertEquals(5L, AppUpdaterPlugin.positiveUpdateInteger(Double.valueOf(5.0)));
        assertEquals(9007199254740991L, AppUpdaterPlugin.positiveUpdateInteger(9007199254740991L));
    }

    @Test
    public void rejectsMissingNonNumericFractionalAndUnsafeValues() {
        Object[] invalid = { null, "5", true, 0, -1L, 1.5, Double.NaN,
            Double.POSITIVE_INFINITY, 9007199254740992L, Long.MAX_VALUE };
        for (Object value : invalid) {
            assertEquals("Invalid update value: " + value, 0L, AppUpdaterPlugin.positiveUpdateInteger(value));
        }
    }
}

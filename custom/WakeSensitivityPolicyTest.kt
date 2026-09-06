package ai.closepaw.ui.capsule.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WakeSensitivityPolicyTest {

    @Test
    fun defaultThresholdIsCalibratedToPoint85() {
        assertEquals(0.85f, HandsFreeWakeSettings.DEFAULT_THRESHOLD, 0.0001f)
    }

    @Test
    fun thresholdIsClampedToSafeUiRange() {
        assertEquals(0.50f, HandsFreeWakeSettings.normalize(0.10f), 0.0001f)
        assertEquals(0.85f, HandsFreeWakeSettings.normalize(0.85f), 0.0001f)
        assertEquals(0.99f, HandsFreeWakeSettings.normalize(1.50f), 0.0001f)
    }

    @Test
    fun fullWindowAtOrAboveConfiguredThresholdTriggers() {
        assertTrue(
            HandsFreeWakeSettings.shouldTrigger(
                probabilities = listOf(0.86f, 0.88f, 0.90f, 0.87f, 0.89f),
                windowSize = 5,
                threshold = 0.85f,
            )
        )
    }

    @Test
    fun singleHighSpikeDoesNotTriggerWithoutSustainedWakeEvidence() {
        assertFalse(
            HandsFreeWakeSettings.shouldTrigger(
                probabilities = listOf(0.05f, 0.06f, 0.95f, 0.08f, 0.07f),
                windowSize = 5,
                threshold = 0.85f,
            )
        )
    }

    @Test
    fun incompleteWindowNeverTriggers() {
        assertFalse(
            HandsFreeWakeSettings.shouldTrigger(
                probabilities = listOf(0.99f, 0.99f),
                windowSize = 5,
                threshold = 0.85f,
            )
        )
    }
}

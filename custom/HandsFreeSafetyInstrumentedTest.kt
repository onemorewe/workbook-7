package ai.closepaw.ui.capsule.voice

import android.Manifest
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.test.platform.app.InstrumentationRegistry
import junit.framework.TestCase
import kotlinx.coroutines.runBlocking

class HandsFreeSafetyInstrumentedTest : TestCase() {

    fun testEnablingWithoutMicrophonePermissionIsBlockedWithoutStartingService() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val permission = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
        if (permission == PackageManager.PERMISSION_GRANTED) return

        val error = HandsFreeVoiceService.setEnabled(context, true)

        assertNotNull(error)
        assertFalse(HandsFreeVoiceService.isEnabled(context))
    }

    fun testMicroWakeWordNativeRuntimeLoadsAndAcceptsAudio() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val detector = LocalWakeWordDetector(context)
        try {
            val initialized = detector.initialize()
            if (initialized.isFailure) throw initialized.exceptionOrNull()!!
            detector.accept24k(ShortArray(480), 480)
        } finally {
            detector.close()
        }
    }
}

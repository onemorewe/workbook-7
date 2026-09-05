package ai.closepaw.ui.capsule.voice

import android.Manifest
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HandsFreeSafetyInstrumentedTest {

    @Test
    fun enablingWithoutMicrophonePermissionIsBlockedWithoutStartingService() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val permission = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
        assumeTrue("Fresh emulator should not have RECORD_AUDIO granted", permission != PackageManager.PERMISSION_GRANTED)

        val error = HandsFreeVoiceService.setEnabled(context, true)

        assertNotNull(error)
        assertFalse(HandsFreeVoiceService.isEnabled(context))
    }

    @Test
    fun microWakeWordNativeRuntimeLoadsAndAcceptsAudio() = runBlocking {
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

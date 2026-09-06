package ai.closepaw.ui.capsule.voice

import android.Manifest
import android.content.Intent
import ai.closepaw.app.MainActivity
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import java.io.ByteArrayOutputStream
import junit.framework.TestCase

/**
 * Black-box UI smoke test: launch the real app, open the drawer, enter Settings, open the dedicated
 * Voice & Runtime screen, and press the real hands-free button. A fresh emulator intentionally has
 * no OpenAI/Codex credentials, so startup must fail visibly in the panel instead of crashing.
 */
class VoiceRuntimeUiInstrumentedTest : TestCase() {

    fun testVoiceRuntimePanelNavigationAndHandsFreeButtonDoNotCrash() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val device = UiDevice.getInstance(instrumentation)

        runCatching {
            instrumentation.uiAutomation.grantRuntimePermission(
                context.packageName,
                Manifest.permission.RECORD_AUDIO,
            )
        }

        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName)
            ?: throw AssertionError("No launch intent for ${context.packageName}")
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)

        // MainActivity's debug/eval bypass checks presence of both extras. Use an explicit blank
        // String instead of a nullable extra: hasExtra(EXTRA_GOAL) is then unambiguous after Intent
        // parceling, while MainActivityIntentPayload still normalizes the blank goal to no task.
        launch.putExtra(MainActivity.EXTRA_FRESH_SESSION, true)
        launch.putExtra(MainActivity.EXTRA_GOAL, "")

        // startActivitySync waits until the real target Activity is launched instead of racing an
        // asynchronous Context.startActivity() against the first UiAutomator lookup on a cold VM.
        instrumentation.startActivitySync(launch)
        device.waitForIdle()

        val menu = device.wait(Until.findObject(By.desc("Open menu")), 30_000L)
        if (menu == null) {
            val hierarchy = ByteArrayOutputStream().use { out ->
                runCatching { device.dumpWindowHierarchy(out) }
                out.toString(Charsets.UTF_8.name()).take(12_000)
            }
            fail(
                "Chat header never appeared after synchronous debug launch; " +
                    "currentPackage=${device.currentPackageName}; hierarchy=$hierarchy"
            )
        }
        menu.click()

        val settings = device.wait(Until.findObject(By.text("Settings")), 5_000L)
        assertNotNull("Settings row not found in navigation drawer", settings)
        settings.click()

        val voiceRuntime = device.wait(Until.findObject(By.text("Voice & Runtime")), 5_000L)
        assertNotNull("Voice & Runtime row not found", voiceRuntime)
        voiceRuntime.click()

        assertNotNull(
            "Dedicated Voice & Runtime page did not render Agent reasoning section",
            device.wait(Until.findObject(By.text("Agent reasoning")), 5_000L),
        )
        assertNotNull("Normal microphone section missing", device.findObject(By.text("Normal microphone")))
        assertNotNull("Hands-free section missing", device.findObject(By.text("Hands-free")))

        val enable = device.wait(Until.findObject(By.text("Turn on hands-free")), 5_000L)
        assertNotNull("Hands-free enable button missing", enable)
        enable.click()

        // No credentials are installed in this hermetic emulator. The expected result is a visible
        // preflight error while the app stays alive on the same screen, never a process crash.
        device.waitForIdle()
        assertNotNull(
            "App left/crashed after pressing hands-free",
            device.wait(Until.findObject(By.text("Voice & Runtime")), 5_000L),
        )
    }
}

package ai.closepaw.ui.capsule.voice

import android.Manifest
import android.content.Intent
import ai.closepaw.app.MainActivity
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiScrollable
import androidx.test.uiautomator.UiSelector
import androidx.test.uiautomator.Until
import java.io.ByteArrayOutputStream
import java.io.File
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

        // Capture while the failing Activity is still alive, not after instrumentation exits.
        // This fresh CI emulator has no provider credentials or personal app data.
        fun captureStage(stage: String): String {
            val directory = File(context.filesDir, "ui-diagnostics")
            val errors = mutableListOf<String>()
            if (!directory.isDirectory && !directory.mkdirs()) {
                return "Cannot create scoped diagnostic directory"
            }
            runCatching {
                check(device.takeScreenshot(File(directory, "$stage.png"))) { "takeScreenshot returned false" }
            }.onFailure { errors += "screenshot: ${it.javaClass.name}: ${it.message}" }
            runCatching {
                File(directory, "$stage.xml").outputStream().use { device.dumpWindowHierarchy(it) }
            }.onFailure { errors += "hierarchy: ${it.javaClass.name}: ${it.message}" }
            val details = if (errors.isEmpty()) "OK" else errors.joinToString("\n")
            runCatching { File(directory, "$stage-errors.txt").writeText(details) }
                .onFailure { errors += "error-file: ${it.javaClass.name}: ${it.message}" }
            return if (errors.isEmpty()) "Saved $stage" else errors.joinToString("; ")
        }

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

        var menu = device.wait(Until.findObject(By.desc("Open menu")), 30_000L)
        if (menu == null) {
            println(captureStage("launch-header-failure"))
            // CI150/151 captured an external launcher ANR over the launched Activity. Recover
            // only that exact, unambiguous system dialog once; an app ANR must still fail.
            val systemTitles = device.findObjects(By.pkg("android").res("android", "alertTitle"))
            val dialog = device.findObjects(By.pkg("android").res("android", "parentPanel")).singleOrNull()
            val title = dialog?.findObjects(By.res("android", "alertTitle"))?.singleOrNull()
            val close = dialog?.findObjects(By.res("android", "aerr_close").text("Close app"))?.singleOrNull()
            val quickstepTitle = By.pkg("android").res("android", "alertTitle").text("Quickstep isn't responding")
            if (device.currentPackageName == "android" && systemTitles.size == 1 &&
                title?.text == "Quickstep isn't responding" && close != null
            ) {
                println("Closing one exact Quickstep system ANR before retrying the debug Activity launch")
                close.click()
                assertTrue("Quickstep system ANR did not close", device.wait(Until.gone(quickstepTitle), 5_000L))
                instrumentation.startActivitySync(launch)
                device.waitForIdle()
                menu = device.wait(Until.findObject(By.desc("Open menu")), 30_000L)
            }
        }
        if (menu == null) {
            println(captureStage("launch-final-header-failure"))
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
            "Dedicated Voice & Runtime page did not render Agent section",
            device.wait(Until.findObject(By.text("Agent")), 5_000L),
        )
        assertNotNull("Shared transcription section missing", device.findObject(By.text("Transcription · normal mic + Jarvis")))
        assertNotNull("Hands-free section missing", device.findObject(By.text("Hands-free")))
        println(captureStage("panel-before-scroll"))

        // The button follows runtime details and a slider inside the real scrollable page.
        // A visible section heading does not imply that its controls fit in the viewport.
        fun scrollToText(text: String, stage: String) {
            val result = runCatching {
                UiScrollable(UiSelector().scrollable(true))
                    .setAsVerticalList()
                    .setMaxSearchSwipes(6)
                    .scrollIntoView(UiSelector().text(text))
            }
            // CI149's capture showed the target on-screen after a false legacy scroll result.
            // Judge success by the actual target after the bounded gesture, not that Boolean.
            if (device.wait(Until.findObject(By.text(text)), 5_000L) != null) return
            val capture = captureStage("$stage-failure")
            fail(
                "Could not scroll to '$text'; currentPackage=${device.currentPackageName}; " +
                    "scrollResult=${result.getOrNull()}; scrollError=${result.exceptionOrNull()?.message}; diagnostics=$capture"
            )
        }

        scrollToText("Turn on hands-free", "enable-button")
        val enable = device.wait(Until.findObject(By.text("Turn on hands-free")), 5_000L)
        assertNotNull("Hands-free enable button missing", enable)
        val errorBeforeClick = HandsFreeVoiceService.lastError.value
        enable.click()

        // No credentials are installed in this hermetic emulator. The expected result is a visible
        // preflight error while the app stays alive on the same screen, never a process crash.
        device.waitForIdle()
        val expectedError = "Last error: OpenAI API key is required for live transcription"
        scrollToText(expectedError, "preflight-error")
        try {
            assertNotNull(
                "Missing credential preflight error was not rendered",
                device.wait(Until.findObject(By.text(expectedError)), 5_000L),
            )
            assertEquals("App left/crashed after pressing hands-free", context.packageName, device.currentPackageName)
            assertFalse("Hands-free started without a transcription credential", HandsFreeVoiceService.isEnabled(context))
        } catch (failure: AssertionError) {
            // Capture only after failure, so diagnostic I/O does not change success timing.
            val state = runCatching {
                fun bounded(value: String?) = value?.take(300)?.replace('\n', ' ') ?: "null"
                "errorBeforeClick=${bounded(errorBeforeClick)}; " +
                    "lastError=${bounded(HandsFreeVoiceService.lastError.value)}; " +
                    "runtimeStatus=${bounded(HandsFreeVoiceService.runtimeStatus.value)}; " +
                    "isEnabled=${HandsFreeVoiceService.isEnabled(context)}; " +
                    "currentPackage=${bounded(device.currentPackageName)}"
            }.getOrElse { "state-read: ${it.javaClass.name}: ${it.message?.take(300)}" }
            println("Preflight assertion failure state: $state")
            println(captureStage("preflight-assertion-failure"))
            runCatching {
                File(context.filesDir, "ui-diagnostics/preflight-assertion-failure-state.txt").writeText(state)
            }.onFailure { println("state-file: ${it.javaClass.name}: ${it.message?.take(300)}") }
            throw failure
        }
    }
}

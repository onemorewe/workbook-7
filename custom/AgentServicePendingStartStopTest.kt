package ai.closepaw.app

import android.content.SharedPreferences
import ai.closepaw.protocol.AgentEvent
import ai.closepaw.protocol.Op
import ai.closepaw.protocol.SessionId
import ai.closepaw.protocol.SessionEndReason
import ai.closepaw.protocol.SessionState
import ai.closepaw.session.AgentSession
import ai.closepaw.session.SessionServices
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.mockkObject
import io.mockk.spyk
import io.mockk.unmockkObject
import io.mockk.verify
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.time.Duration.Companion.seconds
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Regression against the real AgentService orchestration; original Stop case RED in CI 145.
 *
 * No service lifecycle method, runAgent(), stopAgent(), or submitOps() is stubbed.
 * Only Android prefs and the external session-construction/session-execution boundary
 * are replaced. The factory blocks on Dispatchers.Default, exactly where production
 * calls it; no test copy of the startup/cancellation logic is involved.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AgentServicePendingStartStopTest {
    private val dispatcher = StandardTestDispatcher()
    private val factoryEntered = CountDownLatch(1)
    private val releaseFactory = CountDownLatch(1)
    private lateinit var service: AgentService
    private lateinit var createdSession: AgentSession

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)

        // AppSettingsStore's constructor reads prefs before a constructor mock could
        // intercept load(). Keep the real store and supply inert defaults instead.
        val prefs = mockk<SharedPreferences>()
        every { prefs.getString(any(), any()) } answers { secondArg<String?>() }
        every { prefs.getBoolean(any(), any()) } answers { secondArg<Boolean>() }
        service = spyk(AgentService())
        every { service.getSharedPreferences(any(), any()) } returns prefs

        // onServiceConnected creates Android windows/receivers. Set only its active
        // flag here: this is a host orchestration test, not Android lifecycle proof.
        AgentService::class.java.getDeclaredField("isServiceActive").apply {
            isAccessible = true
            setBoolean(service, true)
        }

        val services = mockk<SessionServices>(relaxed = true)
        createdSession = mockk<AgentSession>()
        every { createdSession.sessionId } returns SessionId("pending-start-offline")
        every { createdSession.state } returns MutableStateFlow(SessionState.Idle)
        every { createdSession.events } returns MutableSharedFlow<AgentEvent>()
        every { createdSession.getServices() } returns services
        coEvery { createdSession.submit(any()) } returns Unit

        // create is a normal fun, not suspend: every/CountDownLatch is intentional.
        // Mocking this whole boundary prevents platform/LLM/auth/file initialization.
        mockkObject(AgentSession.Companion)
        every {
            AgentSession.create(
                config = any(),
                service = service,
                scope = any(),
                authStore = any(),
                baseUrlOverrides = any(),
                visualizer = any(),
                overlayTouchGate = any(),
            )
        } answers {
            factoryEntered.countDown()
            check(releaseFactory.await(5, TimeUnit.SECONDS)) {
                "Test harness did not release the session factory within 5 seconds"
            }
            createdSession
        }
    }

    @After
    fun tearDown() {
        releaseFactory.countDown()
        if (::service.isInitialized) service.serviceScope.cancel()
        unmockkObject(AgentSession.Companion)
        Dispatchers.resetMain()
    }

    @Test
    fun `control - completed startup publishes session and submits goal`() =
        runTest(dispatcher, timeout = 15.seconds) {
            try {
                service.runAgent("offline synthetic goal")
                runCurrent()
                assertTrue("Real runAgent did not reach mocked factory", factoryEntered.await(5, TimeUnit.SECONDS))
                val startup = service.serviceScope.coroutineContext[Job]!!.children.single()
                assertNull(service.getActiveSession())

                releaseFactory.countDown()
                startup.join()
                runCurrent()

                assertSame(createdSession, service.getActiveSession())
                coVerify(exactly = 1) {
                    createdSession.submit(Op.UserInput(text = "offline synthetic goal"))
                }
                coVerify(exactly = 0) { createdSession.submit(Op.Shutdown) }
            } finally {
                releaseFactory.countDown()
                service.serviceScope.cancel()
                service.serviceScope.coroutineContext[Job]!!.join()
            }
        }

    @Test
    fun `Stop while factory is pending rejects late session and shuts it down`() =
        runTest(dispatcher, timeout = 15.seconds) {
            try {
                service.runAgent("offline synthetic goal")
                runCurrent()
                assertTrue("Real runAgent did not reach mocked factory", factoryEntered.await(5, TimeUnit.SECONDS))
                val startup = service.serviceScope.coroutineContext[Job]!!.children.single()
                assertNull(service.getActiveSession())

                // The caller stops while create() is in progress and no session has
                // been published. Only now may the late factory result be returned.
                service.stopAgent()
                runCurrent()
                assertEquals("\ud83d\uded1 Agent stopped", AgentService.statusFlow.value)
                releaseFactory.countDown()
                startup.join()
                runCurrent()

                coVerify(exactly = 0) { createdSession.submit(any<Op.UserInput>()) }
                assertNull("A stopped startup must not publish its late session", service.getActiveSession())
                coVerify(exactly = 1) { createdSession.submit(Op.Shutdown) }
                assertEquals("\ud83d\uded1 Agent stopped", AgentService.statusFlow.value)
            } finally {
                releaseFactory.countDown()
                service.serviceScope.cancel()
                service.serviceScope.coroutineContext[Job]!!.join()
            }
        }

    @Test
    fun `pending Stop sends terminal capsule notification before factory returns`() = serviceTest {
        val overlay = attachOverlay()
        val startup = beginBlockedStartup()

        service.stopAgent()
        runCurrent()

        // This checks the service/controller contract, not rendered Android windows.
        verify(exactly = 1) { overlay.onSessionCompleted(SessionEndReason.USER_STOPPED) }
        assertNull(service.getActiveSession())
        releaseFactory.countDown()
        startup.join()
        runCurrent()
        verify(exactly = 1) { overlay.onSessionCompleted(SessionEndReason.USER_STOPPED) }
    }

    @Test
    fun `Stop on published session keeps session driven terminal notification`() = serviceTest {
        val overlay = attachOverlay()
        val startup = beginBlockedStartup()
        releaseFactory.countDown()
        startup.join()
        runCurrent()
        assertSame(createdSession, service.getActiveSession())

        service.stopAgent()
        runCurrent()

        coVerify(exactly = 1) { createdSession.submit(Op.Shutdown) }
        verify(exactly = 0) { overlay.onSessionCompleted(any()) }
    }

    @Test
    fun `new startup stays current when older factory finishes late`() = serviceTest {
        val newerSession = fakeSession("newer-start")
        val calls = AtomicInteger()
        replaceFactory {
            if (calls.getAndIncrement() == 0) {
                awaitFactoryRelease()
                createdSession
            } else newerSession
        }
        val olderStartup = beginBlockedStartup()
        service.runAgent("newer synthetic goal")
        val newerStartup = service.serviceScope.coroutineContext[Job]!!.children.first { it !== olderStartup }
        runCurrent()
        newerStartup.join()
        runCurrent()
        assertSame(newerSession, service.getActiveSession())

        releaseFactory.countDown()
        olderStartup.join()
        runCurrent()

        assertSame(newerSession, service.getActiveSession())
        coVerify(exactly = 0) { createdSession.submit(any<Op.UserInput>()) }
        coVerify(exactly = 1) { createdSession.submit(Op.Shutdown) }
        coVerify(exactly = 1) { newerSession.submit(Op.UserInput("newer synthetic goal")) }
        coVerify(exactly = 0) { newerSession.submit(Op.Shutdown) }
    }

    @Test
    fun `older factory failure cannot hide or overwrite newer startup status`() = serviceTest {
        service.stopAgent()
        val overlay = attachOverlay()
        val newerSession = fakeSession("newer-after-failure")
        val calls = AtomicInteger()
        replaceFactory {
            if (calls.getAndIncrement() == 0) {
                awaitFactoryRelease()
                throw IllegalStateException("synthetic old factory failure")
            } else newerSession
        }
        val olderStartup = beginBlockedStartup()
        service.runAgent("newer synthetic goal")
        val newerStartup = service.serviceScope.coroutineContext[Job]!!.children.first { it !== olderStartup }
        runCurrent()
        newerStartup.join()
        runCurrent()

        releaseFactory.countDown()
        olderStartup.join()
        runCurrent()

        assertSame(newerSession, service.getActiveSession())
        assertEquals("\ud83d\uded1 Agent stopped", AgentService.statusFlow.value)
        verify(exactly = 0) { overlay.hideAll() }
        coVerify(exactly = 1) { newerSession.submit(Op.UserInput("newer synthetic goal")) }
        service.stopAgent()
        runCurrent()
        // Old cleanup must not leave a pending marker that terminates the newer UI.
        verify(exactly = 0) { overlay.onSessionCompleted(any()) }
    }

    @Test
    fun `factory cancellation propagates without failed status or leftover pending UI`() = serviceTest {
        service.stopAgent()
        val overlay = attachOverlay()
        replaceFactory {
            awaitFactoryRelease()
            throw CancellationException("synthetic factory cancellation")
        }
        val startup = beginBlockedStartup()
        releaseFactory.countDown()
        startup.join()
        runCurrent()

        assertTrue(startup.isCancelled)
        assertNull(service.getActiveSession())
        assertEquals("\ud83d\uded1 Agent stopped", AgentService.statusFlow.value)
        verify(exactly = 0) { overlay.hideAll() }
        service.stopAgent()
        runCurrent()
        verify(exactly = 0) { overlay.onSessionCompleted(any()) }
    }

    @Test
    fun `cancelled service scope still shuts down late factory result`() = serviceTest {
        service.stopAgent()
        val startup = beginBlockedStartup()

        service.serviceScope.cancel()
        releaseFactory.countDown()
        startup.join()
        runCurrent()

        assertTrue(startup.isCancelled)
        assertNull(service.getActiveSession())
        coVerify(exactly = 0) { createdSession.submit(any<Op.UserInput>()) }
        coVerify(exactly = 1) { createdSession.submit(Op.Shutdown) }
        assertEquals("\ud83d\uded1 Agent stopped", AgentService.statusFlow.value)
    }

    @Test
    fun `Stop before queued startup runs does not call factory`() = serviceTest {
        releaseFactory.countDown()
        service.runAgent("offline synthetic goal")
        val startup = service.serviceScope.coroutineContext[Job]!!.children.single()

        service.stopAgent()
        runCurrent()
        startup.join()

        verify(exactly = 0) {
            AgentSession.create(any(), service, any(), any(), any(), any(), any())
        }
        assertNull(service.getActiveSession())
        assertEquals("\ud83d\uded1 Agent stopped", AgentService.statusFlow.value)
    }

    private fun serviceTest(block: suspend TestScope.() -> Unit) =
        runTest(dispatcher, timeout = 15.seconds) {
            try {
                block()
            } finally {
                releaseFactory.countDown()
                service.serviceScope.cancel()
                service.serviceScope.coroutineContext[Job]!!.join()
            }
        }

    private fun TestScope.beginBlockedStartup(): Job {
        service.runAgent("offline synthetic goal")
        runCurrent()
        assertTrue("Real runAgent did not reach mocked factory", factoryEntered.await(5, TimeUnit.SECONDS))
        return service.serviceScope.coroutineContext[Job]!!.children.single()
    }

    private fun awaitFactoryRelease() {
        factoryEntered.countDown()
        check(releaseFactory.await(5, TimeUnit.SECONDS)) { "Factory barrier timed out" }
    }

    private fun replaceFactory(factory: () -> AgentSession) {
        every {
            AgentSession.create(any(), service, any(), any(), any(), any(), any())
        } answers { factory() }
    }

    private fun fakeSession(id: String): AgentSession = mockk<AgentSession>().also { candidate ->
        every { candidate.sessionId } returns SessionId(id)
        every { candidate.state } returns MutableStateFlow(SessionState.Idle)
        every { candidate.events } returns MutableSharedFlow<AgentEvent>()
        every { candidate.getServices() } returns mockk<SessionServices>(relaxed = true)
        coEvery { candidate.submit(any()) } returns Unit
    }

    private fun attachOverlay(): ServiceOverlayController =
        mockk<ServiceOverlayController>(relaxed = true).also { overlay ->
            AgentService::class.java.getDeclaredField("overlayController").apply {
                isAccessible = true
                set(service, overlay)
            }
        }
}

package ai.closepaw.app

import android.content.SharedPreferences
import ai.closepaw.protocol.AgentEvent
import ai.closepaw.protocol.Op
import ai.closepaw.protocol.SessionId
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
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
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
 * Candidate regression against the real AgentService orchestration. NOT_RUN locally.
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
}

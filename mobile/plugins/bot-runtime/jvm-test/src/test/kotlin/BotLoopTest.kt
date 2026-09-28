import com.barantheviber.tradingbot.BotLoop
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BotLoopTest {
  /** A bot that runs until stopped; start can be held open to stop in the middle of it. */
  private class FakeBot(private val startGate: CountDownLatch? = null, private val failStart: String? = null) : BotLoop.Bot {
    val starts: MutableList<String> = Collections.synchronizedList(mutableListOf())
    val stopped = CountDownLatch(1)
    @Volatile var stops = 0
    @Volatile var running = false
    @Volatile var error: String? = null

    override fun start(config: String) {
      starts.add(config)
      startGate?.await(5, TimeUnit.SECONDS)
      if (failStart != null) throw RuntimeException("$failStart\n  at python traceback")
      running = true
    }

    override fun status() = BotLoop.Status(running, error)

    override fun stop() {
      stops += 1
      running = false
      stopped.countDown()
    }
  }

  private class Recorder : BotLoop.Events {
    val phases: MutableList<String> = Collections.synchronizedList(mutableListOf())
    val messages: MutableList<String?> = Collections.synchronizedList(mutableListOf())
    val finishedIds: MutableList<Int> = Collections.synchronizedList(mutableListOf())
    @Volatile var ended = 0
    val done = CountDownLatch(1)

    override fun phase(phase: String, message: String?) {
      phases.add(phase)
      messages.add(message)
    }

    override fun ended() {
      ended += 1
    }

    override fun finished(startId: Int) {
      finishedIds.add(startId)
      done.countDown()
    }

    fun waitFor(phase: String) {
      val until = System.currentTimeMillis() + 5_000
      while (phase !in phases && System.currentTimeMillis() < until) Thread.sleep(10)
      assertTrue(phase in phases, "never reached $phase: $phases")
    }
  }

  private val loops = mutableListOf<BotLoop>()

  // A watch interval far longer than any test: stopping must not wait for the next status check.
  private fun loop(bot: FakeBot, events: Recorder) = BotLoop(bot, events, watchEveryMs = 60_000L).also { loops.add(it) }

  @AfterTest
  fun cleanUp() {
    loops.forEach { it.shutdown() }
  }

  @Test
  fun `Durdur stops a running bot right away`() {
    val bot = FakeBot()
    val events = Recorder()
    val loop = loop(bot, events)
    loop.start("cfg", 1)
    events.waitFor("running")

    loop.stop(2)
    assertTrue(bot.stopped.await(2, TimeUnit.SECONDS), "bot.stop() was never called")
    assertTrue(events.done.await(2, TimeUnit.SECONDS))
    assertEquals(listOf("starting", "running", "stopping", "stopped"), events.phases)
    assertEquals(listOf(2), events.finishedIds)
    assertEquals(0, events.ended, "a user stop is not an end by itself")
    assertFalse(loop.isActive)
  }

  @Test
  fun `Durdur during a slow start stops the bot once it is up`() {
    val gate = CountDownLatch(1)
    val bot = FakeBot(startGate = gate)
    val events = Recorder()
    val loop = loop(bot, events)
    loop.start("cfg", 1)
    loop.stop(2)
    gate.countDown()

    assertTrue(bot.stopped.await(2, TimeUnit.SECONDS))
    assertTrue(events.done.await(2, TimeUnit.SECONDS))
    assertFalse("running" in events.phases, "shown as running after Durdur: ${events.phases}")
    assertEquals("stopped", events.phases.last())
    assertEquals(listOf(2), events.finishedIds)
  }

  @Test
  fun `a restart right after Durdur runs the new setup and keeps the service`() {
    val bot = FakeBot()
    val events = Recorder()
    val loop = loop(bot, events)
    loop.start("old", 1)
    events.waitFor("running")

    loop.stop(2)
    loop.start("new", 3)
    val until = System.currentTimeMillis() + 5_000
    while (bot.starts.size < 2 && System.currentTimeMillis() < until) Thread.sleep(10)

    assertEquals(listOf("old", "new"), bot.starts)
    assertEquals(1, bot.stops)
    assertTrue(loop.isActive)
    assertEquals(emptyList(), events.finishedIds, "the service must not stop itself under the new bot")
  }

  @Test
  fun `a bot that stops by itself is reported with its error`() {
    val bot = FakeBot()
    val events = Recorder()
    val loop = BotLoop(bot, events, watchEveryMs = 20L).also { loops.add(it) }
    loop.start("cfg", 1)
    events.waitFor("running")

    bot.error = "API port 47821 is in use"
    bot.running = false
    assertTrue(events.done.await(2, TimeUnit.SECONDS))
    assertEquals("error", events.phases.last())
    assertEquals("API port 47821 is in use", events.messages.last())
    assertEquals(1, events.ended)
    assertEquals(listOf(1), events.finishedIds)
    assertFalse(loop.isActive)
  }

  @Test
  fun `a failed start shows the first line of the error`() {
    val bot = FakeBot(failStart = "RuntimeStartError: API_TOKEN en az 16 karakter olmalı")
    val events = Recorder()
    val loop = loop(bot, events)
    loop.start("cfg", 1)

    assertTrue(events.done.await(2, TimeUnit.SECONDS))
    assertEquals("error", events.phases.last())
    assertEquals("RuntimeStartError: API_TOKEN en az 16 karakter olmalı", events.messages.last())
    assertEquals(1, events.ended)
    assertFalse(loop.isActive)
  }

  @Test
  fun `a second start while running is ignored`() {
    val bot = FakeBot()
    val events = Recorder()
    val loop = loop(bot, events)
    loop.start("cfg", 1)
    events.waitFor("running")
    loop.start("other", 2)
    Thread.sleep(50)
    assertEquals(listOf("cfg"), bot.starts)
  }
}

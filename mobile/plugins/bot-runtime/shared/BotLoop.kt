package com.barantheviber.tradingbot

import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Starts the bot on a worker thread, watches it, and stops it. BotService drives it; it holds no
 * Android classes so a plain JVM test covers it (plugins/bot-runtime/jvm-test).
 *
 * Durdur must stop the bot at once, even while the worker is busy watching it. The watch waits
 * on a lock that stop() wakes, so the stop never queues behind a loop that would not end.
 *
 * Every start and stop carries the service's start id. finished(id) is reported only while no
 * newer start is active, so the service never stops itself under a bot the user just started.
 */
class BotLoop(private val bot: Bot, private val events: Events, private val watchEveryMs: Long = 5_000L) {
  /** The Python side (packaging/android/android_runtime.py). */
  interface Bot {
    fun start(config: String)

    /** running=false once the bot or its API stopped by itself; null if it could not be read. */
    fun status(): Status?
    fun stop()
  }

  data class Status(val running: Boolean, val error: String?)

  interface Events {
    fun phase(phase: String, message: String?)

    /** The bot ended by itself (an error or a clean exit), not through stop(). */
    fun ended()

    /** Nothing runs any more; the service can stop itself with this start id. */
    fun finished(startId: Int)
  }

  private val lock = Object()
  private val worker: ExecutorService = Executors.newSingleThreadExecutor()
  // Guarded by lock. Each start gets a new number; `running` is that of the wanted bot, 0 when
  // none. A watch ends as soon as its number is no longer the wanted one, so a start right after
  // Durdur never keeps the old watch alive in front of the stop.
  private var started = 0
  private var running = 0

  val isActive: Boolean
    get() = synchronized(lock) { running != 0 }

  /** Starts the bot with this config unless one is already running. */
  fun start(config: String, startId: Int) {
    val runId = synchronized(lock) {
      if (running != 0) return
      started += 1
      running = started
      events.phase("starting", null)
      started
    }
    worker.execute { watch(runId, config, startId) }
  }

  /** Durdur: ends the watch now, then stops the bot on the worker. */
  fun stop(startId: Int) {
    synchronized(lock) {
      running = 0
      lock.notifyAll()
      events.phase("stopping", null)
    }
    worker.execute {
      stopQuietly()
      synchronized(lock) {
        if (running == 0) {
          events.phase("stopped", null)
          events.finished(startId)
        }
      }
    }
  }

  /** The service is going away: stops a running bot on the caller's thread. True if one was running. */
  fun shutdown(): Boolean {
    val wasActive = synchronized(lock) {
      val was = running != 0
      running = 0
      lock.notifyAll()
      was
    }
    if (wasActive) stopQuietly()
    worker.shutdown()
    return wasActive
  }

  private fun watch(runId: Int, config: String, startId: Int) {
    try {
      bot.start(config)
    } catch (e: Throwable) {
      endBySelf(runId, "error", readable(e), startId)
      return
    }
    synchronized(lock) {
      if (running != runId) return // Durdur came during the start; its stop runs next on this worker
      events.phase("running", null)
    }
    while (true) {
      synchronized(lock) {
        if (running != runId) return
        try {
          lock.wait(watchEveryMs)
        } catch (e: InterruptedException) {
          return
        }
        if (running != runId) return
      }
      val status = try {
        bot.status()
      } catch (e: Throwable) {
        null
      }
      if (status != null && !status.running) {
        endBySelf(runId, if (status.error != null) "error" else "stopped", status.error, startId)
        return
      }
    }
  }

  private fun endBySelf(runId: Int, phase: String, message: String?, startId: Int) {
    synchronized(lock) {
      if (running != runId) return // stopped meanwhile; the stop reports the end
      running = 0
      events.ended()
      events.phase(phase, message)
      events.finished(startId)
    }
  }

  private fun stopQuietly() {
    try {
      bot.stop()
    } catch (e: Throwable) {
      // the bot's state is in SQLite; nothing else to undo
    }
  }

  companion object {
    /** First line of an exception; PyException messages start with the Python type, e.g. "RuntimeStartError: ...". */
    fun readable(e: Throwable): String {
      val msg = e.message ?: e.javaClass.simpleName
      return msg.lineSequence().firstOrNull()?.take(400) ?: msg
    }
  }
}

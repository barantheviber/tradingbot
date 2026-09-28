package com.barantheviber.tradingbot

/**
 * What the phone remembers about running the bot, so it starts again by itself only when it
 * should: after a phone restart or an app update, only a bot that was running when the phone
 * went down comes back. A bot the user stopped with Durdur, or one that ended by itself, stays
 * stopped. The user moves between the phone and the PC by pressing Durdur on one first, and two
 * bots must never trade the same account.
 *
 * Free of Android classes so a plain JVM test covers it (plugins/bot-runtime/jvm-test).
 */
class RunMemory(private val store: Store) {
  interface Store {
    fun getBoolean(key: String): Boolean
    fun getString(key: String): String?
    fun put(values: Map<String, Any?>)
  }

  /** The bot was started with this config. */
  fun started(config: String) = store.put(mapOf(CONFIG to config, WANTED to true))

  /** The user pressed Durdur. */
  fun stoppedByUser() = store.put(mapOf(WANTED to false))

  /** The bot stopped by itself (an error or a clean exit). */
  fun ended() = store.put(mapOf(WANTED to false))

  /** Config to start with after a restart or an update, or null to stay stopped. */
  fun configToResume(): String? = if (store.getBoolean(WANTED)) store.getString(CONFIG) else null

  /**
   * Config for a start of the service: the one the user just asked for, or, when Android or the
   * boot receiver starts it with none, the remembered one only if the bot should still run.
   */
  fun configForStart(requested: String?): String? = requested ?: configToResume()

  companion object {
    const val WANTED = "wanted"
    const val CONFIG = "config"
  }
}

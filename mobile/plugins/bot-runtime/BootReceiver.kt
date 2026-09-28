package com.barantheviber.tradingbot

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

/**
 * Brings the bot back after the phone restarts or the app is updated, but only if it was
 * running before (the user did not stop it). Both broadcasts are sent by the system only and
 * are allowed to start a foreground service from the background.
 */
class BootReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
    // Only a bot that was running when the phone went down (RunMemory); a stopped one stays stopped.
    val memory = context.getSharedPreferences(BotService.PREFS, Context.MODE_PRIVATE).runMemory()
    if (memory.configToResume() == null) return
    try {
      ContextCompat.startForegroundService(
        context, Intent(context, BotService::class.java).setAction(BotService.ACTION_START)
      )
    } catch (e: Exception) {
      // Android refused the start; the bot stays stopped and the app shows "Başlat" as usual.
    }
  }
}

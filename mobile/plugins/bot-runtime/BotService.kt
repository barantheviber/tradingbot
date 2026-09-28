package com.barantheviber.tradingbot

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.Process
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File

/**
 * Runs the Python bot (packaging/android/android_runtime.py) inside the app, as a foreground
 * service with a permanent notification so Android keeps it alive. Written into the Android
 * project by plugins/withBotRuntime.js; the JS side talks to it through modules/bot-runtime.
 *
 * State for the JS side lives in SharedPreferences "tradingbot_runtime": phase
 * (stopped | starting | running | stopping | error), message, and pid (the process the service
 * runs in, so a phase left over from before a restart is not shown as running).
 */
/** RunMemory (shared/RunMemory.kt) on the service's SharedPreferences. */
fun SharedPreferences.runMemory() = RunMemory(object : RunMemory.Store {
  override fun getBoolean(key: String) = this@runMemory.getBoolean(key, false)
  override fun getString(key: String) = this@runMemory.getString(key, null)
  override fun put(values: Map<String, Any?>) {
    val e = edit()
    for ((key, value) in values) {
      when (value) {
        is Boolean -> e.putBoolean(key, value)
        is String -> e.putString(key, value)
        null -> e.remove(key)
        else -> error("unsupported value for $key")
      }
    }
    e.apply()
  }
})

class BotService : Service() {
  companion object {
    const val PREFS = "tradingbot_runtime"
    const val ACTION_START = "com.barantheviber.tradingbot.START_BOT"
    const val ACTION_STOP = "com.barantheviber.tradingbot.STOP_BOT"
    private const val CHANNEL = "bot"
    private const val NOTIFICATION_ID = 4201
  }

  @Volatile private var wakeLock: PowerManager.WakeLock? = null

  private val prefs by lazy { getSharedPreferences(PREFS, Context.MODE_PRIVATE) }
  private val memory by lazy { prefs.runMemory() }

  /** Start, watch and stop (shared/BotLoop.kt); the Python calls and service lifecycle stay here. */
  private val loop by lazy {
    BotLoop(
      object : BotLoop.Bot {
        override fun start(config: String) {
          if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
          runtime().callAttr("start", File(filesDir, "bot").absolutePath, config)
        }

        override fun status(): BotLoop.Status {
          val status = JSONObject(runtime().callAttr("status").toString())
          return BotLoop.Status(
            status.optBoolean("running", false),
            if (status.isNull("error")) null else status.optString("error"),
          )
        }

        override fun stop() {
          if (Python.isStarted()) runtime().callAttr("stop")
        }
      },
      object : BotLoop.Events {
        override fun phase(phase: String, message: String?) = setState(phase, message)
        override fun ended() = memory.ended()
        override fun finished(startId: Int) = finish(startId)
      },
    )
  }

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    if (intent?.action == ACTION_STOP) {
      memory.stoppedByUser()
      loop.stop(startId)
      return START_NOT_STICKY
    }
    // No config in the intent: Android restarted the service after killing the process (null
    // intent), or BootReceiver started it after a phone restart. Either way it continues only a
    // bot that was running and not stopped by the user.
    val config = memory.configForStart(intent?.getStringExtra("config"))
    if (config == null) {
      if (!loop.isActive) finish(startId)
      return START_NOT_STICKY
    }
    memory.started(config)
    prefs.edit().putInt("pid", Process.myPid()).apply()
    goForeground()
    loop.start(config, startId)
    return START_STICKY
  }

  override fun onDestroy() {
    if (loop.shutdown() && prefs.getString("phase", "stopped") != "error") setState("stopped", null)
    releaseWakeLock()
    super.onDestroy()
  }

  private fun runtime() = Python.getInstance().getModule("android_runtime")

  /** Only for the start id of the request that ended the bot: a newer start keeps the service. */
  private fun finish(startId: Int) {
    releaseWakeLock()
    ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
    stopSelf(startId)
  }

  private fun setState(phase: String, message: String?) {
    prefs.edit().putString("phase", phase).putString("message", message).apply()
  }

  private fun goForeground() {
    val manager = getSystemService(NotificationManager::class.java)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      manager.createNotificationChannel(
        NotificationChannel(CHANNEL, "Trading bot", NotificationManager.IMPORTANCE_LOW).apply {
          description = "Bot çalışırken görünen kalıcı bildirim"
        }
      )
    }
    val open = packageManager.getLaunchIntentForPackage(packageName)
    val pending = PendingIntent.getActivity(
      this, 0, open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )
    val notification: Notification = NotificationCompat.Builder(this, CHANNEL)
      .setContentTitle("Trading bot çalışıyor")
      .setContentText("Paper trading · durdurmak için uygulamayı açın")
      .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
      .setOngoing(true)
      .setContentIntent(pending)
      .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
      .build()
    val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
      ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
    ServiceCompat.startForeground(this, NOTIFICATION_ID, notification, type)
    if (wakeLock == null) {
      // Keeps the CPU awake so the bot's timers and network calls keep running with the screen off.
      wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
        .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "tradingbot:bot")
        .apply { setReferenceCounted(false); acquire() }
    }
  }

  private fun releaseWakeLock() {
    wakeLock?.let { if (it.isHeld) it.release() }
    wakeLock = null
  }
}

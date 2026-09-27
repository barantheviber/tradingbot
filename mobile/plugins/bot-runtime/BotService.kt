package com.barantheviber.tradingbot

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/**
 * Runs the Python bot (packaging/android/android_runtime.py) inside the app, as a foreground
 * service with a permanent notification so Android keeps it alive. Written into the Android
 * project by plugins/withBotRuntime.js; the JS side talks to it through modules/bot-runtime.
 *
 * State for the JS side lives in SharedPreferences "tradingbot_runtime": phase
 * (stopped | starting | running | stopping | error) and message.
 */
class BotService : Service() {
  companion object {
    const val PREFS = "tradingbot_runtime"
    const val ACTION_START = "com.barantheviber.tradingbot.START_BOT"
    const val ACTION_STOP = "com.barantheviber.tradingbot.STOP_BOT"
    private const val CHANNEL = "bot"
    private const val NOTIFICATION_ID = 4201
    private const val MONITOR_EVERY_MS = 5_000L
  }

  private val worker = Executors.newSingleThreadExecutor()
  private var wakeLock: PowerManager.WakeLock? = null
  @Volatile private var active = false

  private val prefs by lazy { getSharedPreferences(PREFS, Context.MODE_PRIVATE) }

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    if (intent?.action == ACTION_STOP) {
      prefs.edit().putBoolean("wanted", false).apply()
      setState("stopping", null)
      worker.execute {
        stopRuntime()
        setState("stopped", null)
        finish()
      }
      return START_NOT_STICKY
    }
    // A null intent means Android restarted the service after killing the process.
    val config = intent?.getStringExtra("config") ?: prefs.getString("config", null)
    if (config == null || (intent == null && !prefs.getBoolean("wanted", false))) {
      finish()
      return START_NOT_STICKY
    }
    prefs.edit().putString("config", config).putBoolean("wanted", true).apply()
    goForeground()
    if (!active) {
      active = true
      setState("starting", null)
      worker.execute { runBot(config) }
    }
    return START_STICKY
  }

  override fun onDestroy() {
    if (active) {
      active = false
      stopRuntime()
      if (prefs.getString("phase", "stopped") != "error") setState("stopped", null)
    }
    releaseWakeLock()
    worker.shutdown()
    super.onDestroy()
  }

  private fun runtime() = Python.getInstance().getModule("android_runtime")

  private fun runBot(config: String) {
    try {
      if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
      runtime().callAttr("start", File(filesDir, "bot").absolutePath, config)
      setState("running", null)
    } catch (e: Throwable) {
      active = false
      prefs.edit().putBoolean("wanted", false).apply()
      setState("error", readable(e))
      finish()
      return
    }
    // Watch the Python side: if the bot or the API stops by itself, report why and end the service.
    while (active) {
      try {
        Thread.sleep(MONITOR_EVERY_MS)
      } catch (e: InterruptedException) {
        return
      }
      if (!active) return
      val status = try {
        JSONObject(runtime().callAttr("status").toString())
      } catch (e: Throwable) {
        null
      }
      if (status != null && !status.optBoolean("running", false)) {
        active = false
        prefs.edit().putBoolean("wanted", false).apply()
        val error = if (status.isNull("error")) null else status.optString("error")
        setState(if (error != null) "error" else "stopped", error)
        finish()
        return
      }
    }
  }

  private fun stopRuntime() {
    active = false
    try {
      if (Python.isStarted()) runtime().callAttr("stop")
    } catch (e: Throwable) {
      // the process is going away anyway; the bot's state is in SQLite
    }
  }

  private fun finish() {
    releaseWakeLock()
    ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
    stopSelf()
  }

  private fun readable(e: Throwable): String {
    val msg = e.message ?: e.javaClass.simpleName
    // PyException messages start with the Python type, e.g. "RuntimeStartError: ..."
    return msg.lineSequence().firstOrNull()?.take(400) ?: msg
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

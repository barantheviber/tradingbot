package expo.modules.botruntime

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.ContextCompat
import java.security.SecureRandom
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/**
 * JS bridge to the app's BotService (written into the app by plugins/withBotRuntime.js, which
 * also bundles Python). The service is addressed by class name so this library module does
 * not need Chaquopy on its classpath.
 */
class BotRuntimeModule : Module() {
  private val context: Context
    get() = appContext.reactContext ?: throw IllegalStateException("React context is not available")

  private fun serviceIntent(action: String) =
    Intent(action).setClassName(context, "${context.packageName}.BotService")

  override fun definition() = ModuleDefinition {
    Name("BotRuntime")

    Function("start") { config: String ->
      context.getSharedPreferences("tradingbot_runtime", Context.MODE_PRIVATE)
        .edit().putString("phase", "starting").putString("message", null).apply()
      ContextCompat.startForegroundService(
        context, serviceIntent("com.barantheviber.tradingbot.START_BOT").putExtra("config", config)
      )
    }

    Function("stop") {
      context.startService(serviceIntent("com.barantheviber.tradingbot.STOP_BOT"))
    }

    Function("getState") {
      val prefs = context.getSharedPreferences("tradingbot_runtime", Context.MODE_PRIVATE)
      mapOf("phase" to (prefs.getString("phase", "stopped") ?: "stopped"), "message" to prefs.getString("message", null))
    }

    /** Random token for the phone's own API (hex, 64 characters). */
    Function("newToken") {
      val bytes = ByteArray(32)
      SecureRandom().nextBytes(bytes)
      bytes.joinToString("") { "%02x".format(it) }
    }

    Function("isIgnoringBatteryOptimizations") {
      val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
      pm.isIgnoringBatteryOptimizations(context.packageName)
    }

    @SuppressLint("BatteryLife")
    Function("requestIgnoreBatteryOptimizations") {
      val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
        .setData(Uri.parse("package:${context.packageName}"))
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      try {
        context.startActivity(intent)
      } catch (e: Exception) {
        context.startActivity(
          Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
      }
    }
  }
}

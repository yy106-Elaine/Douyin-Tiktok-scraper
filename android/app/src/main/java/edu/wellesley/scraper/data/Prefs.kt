package edu.wellesley.scraper.data

import android.content.Context
import androidx.core.content.edit
import edu.wellesley.scraper.BuildConfig
import java.util.UUID

/** Device registration state and backend address. */
class Prefs(context: Context) {

    private val prefs =
        context.applicationContext.getSharedPreferences("scraper", Context.MODE_PRIVATE)

    var apiKey: String?
        get() = prefs.getString(KEY_API, null)
        set(value) = prefs.edit { putString(KEY_API, value) }

    var participantId: String?
        get() = prefs.getString(KEY_PARTICIPANT, null)
        set(value) = prefs.edit { putString(KEY_PARTICIPANT, value) }

    var backendUrl: String
        get() = prefs.getString(KEY_BACKEND, null) ?: BuildConfig.DEFAULT_BACKEND_URL
        set(value) = prefs.edit { putString(KEY_BACKEND, value.trimEnd('/')) }

    /** Random per-install id; never a hardware identifier. */
    val deviceId: String
        get() = prefs.getString(KEY_DEVICE, null) ?: UUID.randomUUID().toString().also {
            prefs.edit { putString(KEY_DEVICE, it) }
        }

    val isRegistered: Boolean
        get() = !apiKey.isNullOrBlank()

    fun clear() = prefs.edit { clear() }

    private companion object {
        const val KEY_API = "api_key"
        const val KEY_PARTICIPANT = "participant_id"
        const val KEY_BACKEND = "backend_url"
        const val KEY_DEVICE = "device_id"
    }
}

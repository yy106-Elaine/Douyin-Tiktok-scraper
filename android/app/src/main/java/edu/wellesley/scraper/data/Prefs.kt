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

    /**
     * The last clipboard text saved as a link, so opening the app twice
     * does not record the same copy twice.
     */
    var lastSavedClipboard: String?
        get() = prefs.getString(KEY_CLIPBOARD, null)
        set(value) = prefs.edit { putString(KEY_CLIPBOARD, value) }

    /**
     * The post named on the last link that was queued.
     *
     * A fingerprint is only evidence when it names the post the link
     * was actually copied from. During an assisted run it goes stale:
     * the capture buffer settles more slowly than the loop copies
     * links, so several videos in a row are reported against whichever
     * post was last read off the screen. Claiming an exact pairing
     * there attributes a video to the wrong caption, which is worse
     * than not pairing at all.
     */
    var lastLinkFingerprint: String?
        get() = prefs.getString(KEY_LINK_FP, null)
        set(value) = prefs.edit { putString(KEY_LINK_FP, value) }

    /** Whether the floating save-link button is wanted. */
    var showSaveButton: Boolean
        get() = prefs.getBoolean(KEY_SAVE_BUTTON, false)
        set(value) = prefs.edit { putBoolean(KEY_SAVE_BUTTON, value) }

    val isRegistered: Boolean
        get() = !apiKey.isNullOrBlank()

    fun clear() = prefs.edit { clear() }

    private companion object {
        const val KEY_API = "api_key"
        const val KEY_PARTICIPANT = "participant_id"
        const val KEY_BACKEND = "backend_url"
        const val KEY_DEVICE = "device_id"
        const val KEY_CLIPBOARD = "last_saved_clipboard"
        const val KEY_SAVE_BUTTON = "show_save_button"
        const val KEY_LINK_FP = "last_link_fingerprint"
    }
}

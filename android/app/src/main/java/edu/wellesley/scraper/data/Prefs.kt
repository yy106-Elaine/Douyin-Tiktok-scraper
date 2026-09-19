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

    /**
     * Display names whose profile has already been visited.
     *
     * The 抖音号 belongs to the account, not the video, so one visit
     * answers it for every post that account ever appears in. Without
     * this the run would open the same profile for every video by a
     * prolific author, and a profile visit is the most expensive step
     * in the loop by a wide margin.
     *
     * Names that turned out to have no id on the page are remembered
     * too. A second attempt would fail the same way and cost the same
     * fifteen seconds.
     */
    var visitedAuthors: Set<String>
        get() = prefs.getStringSet(KEY_VISITED, emptySet()).orEmpty()
        set(value) = prefs.edit { putStringSet(KEY_VISITED, value) }

    /** `name\u0000id` pairs the server has not acknowledged yet. */
    var pendingAuthorIds: Set<String>
        get() = prefs.getStringSet(KEY_PENDING_IDS, emptySet()).orEmpty()
        set(value) = prefs.edit { putStringSet(KEY_PENDING_IDS, value) }

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
        // Suffixed, and bumped when the rule that produced the values
        // changes. The first version picked the first `@名字` in the
        // tree rather than the one belonging to the video in front, so
        // it recorded ids against a neighbour's name -- entries that
        // must not be uploaded now that they are known to be wrong.
        // Renaming the key drops them without asking anyone to
        // reinstall or clear data.
        const val KEY_VISITED = "visited_authors_v2"
        const val KEY_PENDING_IDS = "pending_author_ids_v2"
    }
}

package edu.wellesley.scraper.data

import android.content.Context
import edu.wellesley.scraper.net.ApiClient

/**
 * Holds copied links on disk until the server has them.
 *
 * Writing first and uploading second is the whole point. A link exists
 * for as long as the clipboard holds it and no longer, so a failed
 * upload used to destroy the only copy -- and during an assisted run
 * nobody is watching the toast that says so. Queueing turns a backend
 * that is asleep, a phone off wifi, or a laptop that closed its lid
 * into a delay instead of a loss.
 */
object LinkQueue {

    enum class Queued { ADDED, ALREADY_HAVE_IT, EMPTY }

    /** What one attempt at draining the queue did, for the self-check. */
    data class Drain(val sent: Int, val discarded: Int, val failure: String?)

    suspend fun add(
        context: Context,
        rawText: String,
        sharedAt: Long,
        fingerprint: String?,
    ): Queued {
        val text = rawText.trim()
        if (text.isEmpty()) return Queued.EMPTY

        val dao = CaptureDatabase.get(context).linkDao()
        val prefs = Prefs(context)
        // Douyin leaves the copied text in place, so a video whose copy
        // silently failed would otherwise queue the previous one again.
        if (text == prefs.lastSavedClipboard || dao.countQueued(text) > 0) {
            return Queued.ALREADY_HAVE_IT
        }

        dao.insert(LinkEntity(rawText = text, sharedAt = sharedAt, fingerprint = fingerprint))
        prefs.lastSavedClipboard = text
        return Queued.ADDED
    }

    /**
     * Send what is queued, oldest first, and stop at the first failure
     * that a retry could fix.
     *
     * A 422 means the server could find no link in the text -- that
     * will be just as true tomorrow, so the row goes rather than
     * blocking everything behind it forever.
     */
    suspend fun drain(context: Context, limit: Int = 100): Drain {
        val prefs = Prefs(context)
        val apiKey = prefs.apiKey ?: return Drain(0, 0, "not registered")
        val dao = CaptureDatabase.get(context).linkDao()
        val client = ApiClient(prefs.backendUrl)

        var sent = 0
        var discarded = 0
        for (link in dao.pending(limit)) {
            try {
                client.shareLink(apiKey, link.rawText, link.sharedAt, link.fingerprint)
                dao.delete(link.id)
                sent++
            } catch (error: ApiClient.ApiException) {
                if (error.status == 422) {
                    dao.delete(link.id)
                    discarded++
                    continue
                }
                dao.countFailure(link.id)
                return Drain(sent, discarded, "HTTP ${error.status}")
            } catch (error: Exception) {
                dao.countFailure(link.id)
                return Drain(sent, discarded, error.javaClass.simpleName)
            }
        }
        return Drain(sent, discarded, null)
    }

    suspend fun waiting(context: Context): Int =
        CaptureDatabase.get(context).linkDao().pendingNow()
}

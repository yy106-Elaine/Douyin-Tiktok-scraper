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

        // A fingerprint already spent on an earlier link is stale, not
        // evidence: the server would record an exact pairing to a post
        // this link did not come from. Dropping it falls back to
        // pairing by time, which at least says in the data that it is
        // a heuristic.
        val fresh = fingerprint?.takeIf { it != prefs.lastLinkFingerprint }
        dao.insert(LinkEntity(rawText = text, sharedAt = sharedAt, fingerprint = fresh))
        prefs.lastSavedClipboard = text
        if (fresh != null) prefs.lastLinkFingerprint = fresh
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
    /**
     * How long a link waits before it may be uploaded.
     *
     * Long enough for the profile step -- tap, page load, read, back --
     * to attach a 抖音号 to it. An upload is never urgent: the toast
     * that tells someone their link was saved fires when it is queued,
     * not when it lands.
     */
    const val HOLD_MILLIS = 30_000L

    suspend fun drain(context: Context, limit: Int = 100): Drain {
        val prefs = Prefs(context)
        val apiKey = prefs.apiKey ?: return Drain(0, 0, "not registered")
        val dao = CaptureDatabase.get(context).linkDao()
        val client = ApiClient(prefs.backendUrl)

        var sent = 0
        var discarded = 0
        val ready = dao.pending(limit, System.currentTimeMillis() - HOLD_MILLIS)
        for (link in ready) {
            try {
                client.shareLink(
                    apiKey,
                    link.rawText,
                    link.sharedAt,
                    link.fingerprint,
                    link.authorHandle,
                )
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

    /**
     * Put a 抖音号 on the link queued most recently.
     *
     * That row is this video: the link is queued when it is copied and
     * the profile is opened a step later. Returns false when there is
     * nothing to attach it to, which is the honest outcome if the copy
     * failed -- an id with no video to belong to is not worth keeping.
     */
    suspend fun attachAuthorHandle(context: Context, handle: String): Boolean {
        val dao = CaptureDatabase.get(context).linkDao()
        val newest = dao.newest() ?: return false
        if (newest.authorHandle != null) return false
        // Only a link from this video. An id attached to whatever
        // happened to be queued last would be a claim about a
        // different video, which is the mistake this whole path was
        // rewritten to avoid.
        if (System.currentTimeMillis() - newest.sharedAt > HOLD_MILLIS) return false
        dao.setAuthorHandle(newest.id, handle)
        return true
    }

    suspend fun waiting(context: Context): Int =
        CaptureDatabase.get(context).linkDao().pendingNow()
}

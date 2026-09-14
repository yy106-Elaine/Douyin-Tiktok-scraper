package edu.wellesley.scraper.service

import edu.wellesley.scraper.parser.ParsedPost

/**
 * Holds partially-read posts until they are complete.
 *
 * A post is read many times while it is on screen, and each read sees
 * a different subset of fields (counts animate in, the caption
 * truncates, the music strip scrolls). Committing the first read would
 * store mostly nulls, so reads are merged by fingerprint and only
 * finalised once the post has not been seen for [settleMillis].
 */
class CaptureBuffer(
    private val settleMillis: Long = 5_000L,
    private val now: () -> Long = System::currentTimeMillis,
) {

    private data class Pending(val post: ParsedPost, val firstSeen: Long, val lastSeen: Long)

    private val pending = LinkedHashMap<String, Pending>()

    /** Record an observation. Returns nothing; completed posts come from [drain]. */
    fun observe(post: ParsedPost) {
        val fingerprint = post.fingerprint() ?: return
        val timestamp = now()
        val existing = pending[fingerprint]
        pending[fingerprint] = if (existing == null) {
            Pending(post, timestamp, timestamp)
        } else {
            existing.copy(post = existing.post.mergedWith(post), lastSeen = timestamp)
        }
    }

    /**
     * Remove and return every post that has settled.
     *
     * The timestamp reported for a post is when it was *first* seen,
     * which is the moment it actually reached the participant's
     * screen -- not when the buffer happened to flush it.
     */
    fun drain(force: Boolean = false): List<Pair<ParsedPost, Long>> {
        val timestamp = now()
        val settled = pending.entries.filter {
            force || timestamp - it.value.lastSeen >= settleMillis
        }
        settled.forEach { pending.remove(it.key) }
        return settled.map { it.value.post to it.value.firstSeen }
    }

    fun size(): Int = pending.size
}

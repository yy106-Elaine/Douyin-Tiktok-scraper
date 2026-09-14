package edu.wellesley.scraper.parser

/**
 * One observation of one post, as read off the screen.
 *
 * Every count is kept as the **displayed string** ("12.3万", "74.9K")
 * rather than a number. Converting on the device would throw away the
 * evidence that the value was abbreviated; the backend converts and
 * records that the result is approximate.
 */
data class ParsedPost(
    val platform: String,
    val authorHandle: String? = null,
    val caption: String? = null,
    val music: String? = null,
    val feed: String? = null,
    val likeRaw: String? = null,
    val commentRaw: String? = null,
    val shareRaw: String? = null,
    val saveRaw: String? = null,
    val isAd: Boolean? = null,
    val isAiGenerated: Boolean? = null,
) {
    /**
     * Stable identity for this post across the several partial reads
     * that happen as the user watches it.
     *
     * The accessibility tree never exposes a video id, so this is the
     * best identity available. It collides when one author posts two
     * videos whose captions share a prefix -- a known limitation,
     * documented in docs/METHODOLOGY.md, and resolved for any post the
     * participant also shares a link for.
     */
    fun fingerprint(): String? {
        val author = authorHandle?.trim().orEmpty()
        val head = caption?.trim()?.take(20).orEmpty()
        if (author.isEmpty() && head.isEmpty()) return null
        return "$platform::$author::$head"
    }

    /** True when there is enough here to be worth storing. */
    fun isUsable(): Boolean = fingerprint() != null

    /**
     * Merge a later, possibly more complete read of the same post.
     * Non-null values win; existing values are never overwritten with
     * null, because a field scrolling out of view is not evidence that
     * it changed.
     */
    fun mergedWith(other: ParsedPost): ParsedPost = ParsedPost(
        platform = platform,
        authorHandle = other.authorHandle ?: authorHandle,
        caption = other.caption ?: caption,
        music = other.music ?: music,
        feed = other.feed ?: feed,
        likeRaw = other.likeRaw ?: likeRaw,
        commentRaw = other.commentRaw ?: commentRaw,
        shareRaw = other.shareRaw ?: shareRaw,
        saveRaw = other.saveRaw ?: saveRaw,
        isAd = other.isAd ?: isAd,
        isAiGenerated = other.isAiGenerated ?: isAiGenerated,
    )

    fun toPayload(): Map<String, Any?> = mapOf(
        "author_handle" to authorHandle,
        "caption" to caption,
        "music" to music,
        "feed" to feed,
        "like_raw" to likeRaw,
        "comment_raw" to commentRaw,
        "share_raw" to shareRaw,
        "save_raw" to saveRaw,
        "is_ad" to isAd,
        "is_ai_generated" to isAiGenerated,
    )
}

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
    /**
     * The author's `@handle` -- the stable, unique account identifier,
     * and the only form that can be used to find the account again.
     * Present only when the interface renders it.
     */
    val authorHandle: String? = null,
    /**
     * The author's display name. Not unique, changeable, and often
     * carries emoji. What the feed shows most of the time.
     */
    val authorName: String? = null,
    val caption: String? = null,
    /**
     * The publication date as the interface renders it -- "· 2025-05-31"
     * on TikTok, sometimes relative ("3d ago") instead. Kept verbatim;
     * the server parses what it can.
     *
     * A takedown study needs this: without it the only measurable
     * interval is from when this device happened to see the post, which
     * says more about the viewer's scrolling than about the platform.
     */
    val postedAtRaw: String? = null,
    val music: String? = null,
    val feed: String? = null,
    val likeRaw: String? = null,
    val commentRaw: String? = null,
    val shareRaw: String? = null,
    val saveRaw: String? = null,
    val isAd: Boolean? = null,
    val isAiGenerated: Boolean? = null,
    /**
     * A video id found on screen, when either app happens to expose
     * one. Read passively, so obtaining it costs no interaction with
     * the app and cannot influence what the feed serves next.
     */
    val videoIdHint: String? = null,
) {
    /**
     * Stable identity for this post across the several partial reads
     * that happen as the user watches it.
     *
     * A real video id would be better, and [videoIdHint] supplies one
     * where the interface exposes it. Where it does not, this is the
     * best identity available: it collides when one author posts two
     * videos whose captions share a prefix, which is documented in
     * docs/METHODOLOGY.md.
     */
    fun fingerprint(): String? {
        // Display name first, deliberately: it is the field the feed
        // exposes on nearly every frame, so keying on it keeps a post's
        // identity stable across reads where the handle is absent.
        val author = (authorName ?: authorHandle)?.trim().orEmpty()
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
        authorName = other.authorName ?: authorName,
        caption = other.caption ?: caption,
        postedAtRaw = other.postedAtRaw ?: postedAtRaw,
        music = other.music ?: music,
        feed = other.feed ?: feed,
        likeRaw = other.likeRaw ?: likeRaw,
        commentRaw = other.commentRaw ?: commentRaw,
        shareRaw = other.shareRaw ?: shareRaw,
        saveRaw = other.saveRaw ?: saveRaw,
        isAd = other.isAd ?: isAd,
        isAiGenerated = other.isAiGenerated ?: isAiGenerated,
        videoIdHint = other.videoIdHint ?: videoIdHint,
    )

    fun toPayload(): Map<String, Any?> = mapOf(
        "author_handle" to authorHandle,
        "author_name" to authorName,
        "caption" to caption,
        "posted_at_raw" to postedAtRaw,
        "music" to music,
        "feed" to feed,
        "like_raw" to likeRaw,
        "comment_raw" to commentRaw,
        "share_raw" to shareRaw,
        "save_raw" to saveRaw,
        "is_ad" to isAd,
        "is_ai_generated" to isAiGenerated,
        "video_id_hint" to videoIdHint,
    )
}

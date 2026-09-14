package edu.wellesley.scraper.parser

/**
 * TikTok (international build), English UI.
 *
 * TikTok labels its action buttons for screen readers, so counts are
 * read out of contentDescription rather than guessed from layout
 * position. The selector strings below describe TikTok's own
 * interface and were checked against a working collector; re-verify
 * them against the installed build before a collection run, since
 * they change with the app rather than with Android.
 */
class TikTokParser : PostParser {

    override val platform: String = "tiktok"

    private companion object {
        val LIKE = Regex("""Like video\.\s*([\d.,]+[KMB]?)\s*likes""", RegexOption.IGNORE_CASE)
        val COMMENT = Regex(
            """Read or add comments\.\s*([\d.,]+[KMB]?)\s*comments""", RegexOption.IGNORE_CASE
        )
        val SHARE = Regex("""Share video\.\s*([\d.,]+[KMB]?)\s*shares""", RegexOption.IGNORE_CASE)

        // Favourites carry no count in the description; the number sits in
        // a child node of the button.
        val SAVE_MARKER = Regex("""Favorites""", RegexOption.IGNORE_CASE)
        val COUNT_SHAPED = Regex("""^\d{1,3}([.,]\d+)?[KMB]?$""", RegexOption.IGNORE_CASE)

        val AUTHOR = Regex("""(.+?)\s+profile""", RegexOption.IGNORE_CASE)
        val MUSIC = Regex("""Sound:\s*(.+)""", RegexOption.IGNORE_CASE)

        // The lookbehind matters: the comment BUTTON is described as
        // "Read or add comments. N comments", which would otherwise match
        // here and cause every ordinary frame to be skipped.
        val COMMENT_SHEET = Regex(
            """(?:(?<!or )Add comment|Reply to|Creator liked|View \d+ repl)""",
            RegexOption.IGNORE_CASE,
        )
        val AD_MARKER = Regex("""(?:paid partnership|sponsored|promoted)""", RegexOption.IGNORE_CASE)
        val AI_MARKER = Regex("""AI[- ]generated""", RegexOption.IGNORE_CASE)

        /** Each post's root carries this in its view id. */
        const val POST_CONTAINER = "widget_container"

        /** Below this length a stray label is more likely than a caption. */
        const val CAPTION_MIN_LENGTH = 30

        val FEEDS = setOf("For You", "Following", "Friends", "Explore", "Shop", "LIVE")
        val FEED_SLUGS = mapOf(
            "For You" to "recommend",
            "Following" to "following",
            "Friends" to "friends",
            "Explore" to "explore",
            "Shop" to "shop",
            "LIVE" to "live",
        )
    }

    override fun isPostBoundary(node: FlatNode): Boolean =
        node.viewId?.contains(POST_CONTAINER) == true

    /** The feed tab is the selected one in the top tab bar. */
    override fun feed(nodes: List<FlatNode>): String? {
        val label = nodes.firstOrNull { node ->
            node.selected && FEEDS.any { node.description?.contains(it, true) == true }
        }?.description ?: nodes.firstOrNull { it.selected && it.text in FEEDS }?.text

        val matched = FEEDS.firstOrNull { label?.contains(it, ignoreCase = true) == true }
        return FEED_SLUGS[matched] ?: matched
    }

    override fun shouldSkip(nodes: List<FlatNode>): Boolean =
        NodeTools.anyMatches(nodes, COMMENT_SHEET)

    override fun parse(nodes: List<FlatNode>): ParsedPost? {
        val post = ParsedPost(
            platform = platform,
            authorHandle = NodeTools.firstGroup(nodes, AUTHOR)
                ?: NodeTools.byViewId(nodes, "title")?.text,
            caption = caption(nodes),
            music = NodeTools.firstGroup(nodes, MUSIC),
            likeRaw = NodeTools.firstGroup(nodes, LIKE),
            commentRaw = NodeTools.firstGroup(nodes, COMMENT),
            shareRaw = NodeTools.firstGroup(nodes, SHARE),
            saveRaw = NodeTools.countUnderMarker(nodes, SAVE_MARKER, COUNT_SHAPED),
            isAd = NodeTools.anyMatches(nodes, AD_MARKER),
            isAiGenerated = NodeTools.anyMatches(nodes, AI_MARKER),
        )
        return post.takeIf { it.isUsable() }
    }

    /**
     * The caption has a view id on some builds and none on others, so
     * it falls back to shape: the longest undescribed run of text. The
     * comment-sheet guard is what keeps a long comment from matching
     * that same shape.
     */
    private fun caption(nodes: List<FlatNode>): String? {
        NodeTools.byViewId(nodes, "desc")?.text?.let { return it }
        return nodes
            .filter { it.description == null && (it.text?.length ?: 0) >= CAPTION_MIN_LENGTH }
            .maxByOrNull { it.text!!.length }
            ?.text
    }
}

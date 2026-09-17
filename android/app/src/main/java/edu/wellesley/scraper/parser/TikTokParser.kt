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

        // The favourites button is labelled inconsistently across builds
        // and often carries no count in its own description, so this
        // matches the label loosely and the count is taken from the
        // button's subtree. Unverified against a device; if Saves comes
        // back empty, read the self-check dump and correct it.
        val SAVE_MARKER = Regex(
            """(?:add to |remove from )?favou?rites?|bookmark|collect""",
            RegexOption.IGNORE_CASE,
        )
        /** Some builds put the count straight in the description. */
        val SAVE_INLINE = Regex(
            """([\d.,]+[KMB]?)\s*(?:favou?rites?|bookmarks?)""", RegexOption.IGNORE_CASE
        )
        val COUNT_SHAPED = Regex("""^\d{1,3}([.,]\d+)?[KMB]?$""", RegexOption.IGNORE_CASE)

        val AUTHOR = Regex("""(.+?)\s+profile""", RegexOption.IGNORE_CASE)

        /**
         * A node that is nothing but an `@handle`.
         *
         * Anchored on purpose: captions routinely @-mention other
         * accounts, and matching inside one would attribute the post to
         * whoever it happened to tag. The author's handle, when the
         * feed renders it, is its own node.
         */
        val HANDLE_ONLY = Regex("""^@([A-Za-z0-9._]{2,24})$""")

        /**
         * The caption TextView also renders the "expand" affordance, so
         * the text arrives as "<caption> more" or "<caption>...more".
         * Left in place it adds a meaningless token to every caption,
         * which matters for text analysis. The trade-off is a caption
         * genuinely ending in the word "more" losing that word; carrying
         * a UI control into the data is the worse of the two.
         */
        val TRAILING_EXPAND = Regex("""\s*(?:\.{3}|…)?\s*more\s*$""", RegexOption.IGNORE_CASE)
        val MUSIC = Regex("""Sound:\s*(.+)""", RegexOption.IGNORE_CASE)

        /**
         * Markers that only an open comment sheet produces, each named
         * so a skip says which one fired.
         *
         * Kept deliberately narrow. A first live session skipped 24 of
         * 31 frames on a broader set that included a bare "Add comment"
         * -- which this build also renders on the feed itself -- and
         * losing three quarters of a session is worse than the
         * occasional comment misread as a caption, which the caption
         * rule's length and position checks already make unlikely.
         */
        val COMMENT_SHEET_MARKERS = listOf(
            "reply thread" to Regex("""View \d+ repl(?:y|ies)""", RegexOption.IGNORE_CASE),
            "reply target" to Regex("""Reply to @""", RegexOption.IGNORE_CASE),
            "comments header" to Regex("""^\d+(?:[.,]\d+)?[KMB]? comments$""", RegexOption.IGNORE_CASE),
        )
        val AD_MARKER = Regex("""(?:paid partnership|sponsored|promoted)""", RegexOption.IGNORE_CASE)
        val AI_MARKER = Regex("""AI[- ]generated""", RegexOption.IGNORE_CASE)

        /** Each post's root carries this in its view id. */
        const val POST_CONTAINER = "widget_container"

        /** Below this length a stray label is more likely than a caption. */
        const val CAPTION_MIN_LENGTH = 30

        /** Guard against stripping a short caption into uselessness. */
        const val MIN_STRIPPED_LENGTH = 3

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

    /**
     * Which feed tab is showing.
     *
     * Preferred signal is the selected tab. Not every build reports
     * isSelected on it, and a first live session returned null for
     * every row, so a single visible tab label is accepted as the
     * fallback: when only one is exposed, it is the active one.
     * Several visible and none selected stays unknown rather than
     * guessing.
     */
    override fun feed(nodes: List<FlatNode>): String? {
        val selected = nodes.firstOrNull { node ->
            node.selected && labelOf(node) != null
        }?.let(::labelOf)
        if (selected != null) return FEED_SLUGS[selected] ?: selected

        val visible = nodes.mapNotNull(::labelOf).distinct()
        val only = visible.singleOrNull() ?: return null
        return FEED_SLUGS[only] ?: only
    }

    private fun labelOf(node: FlatNode): String? {
        val text = node.text
        if (text in FEEDS) return text
        val description = node.description ?: return null
        return FEEDS.firstOrNull { description.equals(it, ignoreCase = true) }
    }

    override fun skipReason(nodes: List<FlatNode>): String? =
        COMMENT_SHEET_MARKERS.firstOrNull { (_, pattern) ->
            NodeTools.anyMatches(nodes, pattern)
        }?.let { (name, _) -> "comment sheet open ($name)" }

    override fun parse(nodes: List<FlatNode>): ParsedPost? {
        val post = ParsedPost(
            platform = platform,
            authorHandle = handle(nodes),
            authorName = displayName(nodes),
            caption = caption(nodes),
            music = NodeTools.firstGroup(nodes, MUSIC),
            likeRaw = NodeTools.firstGroup(nodes, LIKE),
            commentRaw = NodeTools.firstGroup(nodes, COMMENT),
            shareRaw = NodeTools.firstGroup(nodes, SHARE),
            saveRaw = NodeTools.firstGroup(nodes, SAVE_INLINE)
                ?: NodeTools.countUnderMarker(nodes, SAVE_MARKER, COUNT_SHAPED)
                ?: NodeTools.byViewId(nodes, "collect_count", "favorite_count")?.text,
            isAd = NodeTools.anyMatches(nodes, AD_MARKER),
            isAiGenerated = NodeTools.anyMatches(nodes, AI_MARKER),
            videoIdHint = IdScanner.bestId(nodes),
        )
        return post.takeIf { it.isUsable() }
    }

    /**
     * The author's `@handle`, which is what identifies the account
     * later -- for finding it again, or for contacting the author.
     * Display names are neither unique nor stable, so they are not a
     * substitute.
     */
    private fun handle(nodes: List<FlatNode>): String? {
        for (node in nodes) {
            for (candidate in listOfNotNull(node.text, node.description)) {
                HANDLE_ONLY.find(candidate.trim())?.let { return it.groupValues[1] }
            }
        }
        // Some builds put the handle in the profile label instead.
        val label = NodeTools.firstGroup(nodes, AUTHOR)?.trim()
        return label?.removePrefix("@")?.takeIf { label.startsWith("@") }
    }

    private fun displayName(nodes: List<FlatNode>): String? =
        NodeTools.firstGroup(nodes, AUTHOR)?.removePrefix("@")?.trim()
            ?: NodeTools.byViewId(nodes, "title")?.text

    /**
     * The caption has a view id on some builds and none on others, so
     * it falls back to shape: the longest undescribed run of text. The
     * comment-sheet guard is what keeps a long comment from matching
     * that same shape.
     */
    private fun caption(nodes: List<FlatNode>): String? {
        val raw = NodeTools.byViewId(nodes, "desc")?.text
            ?: nodes
                .filter { it.description == null && (it.text?.length ?: 0) >= CAPTION_MIN_LENGTH }
                .maxByOrNull { it.text!!.length }
                ?.text
        return raw?.let(::stripExpandAffordance)
    }

    /** Drop the trailing "more" / "...more" the expand control contributes. */
    private fun stripExpandAffordance(caption: String): String {
        val stripped = TRAILING_EXPAND.replace(caption, "").trim()
        // Never strip a caption down to nothing, or near it.
        return if (stripped.length >= MIN_STRIPPED_LENGTH) stripped else caption.trim()
    }
}

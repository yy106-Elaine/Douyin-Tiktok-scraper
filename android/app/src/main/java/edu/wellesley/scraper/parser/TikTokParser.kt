package edu.wellesley.scraper.parser

/**
 * TikTok (international build), English UI.
 *
 * TikTok labels its action buttons for screen readers, so the counts
 * are read out of contentDescription rather than guessed from layout
 * position. Verify these strings against the installed build before a
 * collection run -- they change with the app, not with Android.
 */
class TikTokParser : PostParser {

    override val platform: String = "tiktok"

    private companion object {
        val LIKE = Regex("""Like video\.\s*([\d.,]+[KMB]?)\s*likes""", RegexOption.IGNORE_CASE)
        val COMMENT = Regex("""([\d.,]+[KMB]?)\s*comments""", RegexOption.IGNORE_CASE)
        val SHARE = Regex("""([\d.,]+[KMB]?)\s*shares""", RegexOption.IGNORE_CASE)
        val SAVE = Regex("""([\d.,]+[KMB]?)\s*(?:favorites|bookmarks)""", RegexOption.IGNORE_CASE)
        val AUTHOR = Regex("""@?([\w.\-]+)'s profile""", RegexOption.IGNORE_CASE)

        val COMMENT_SHEET = Regex("""(?:Add comment|Comments \(|Reply to)""", RegexOption.IGNORE_CASE)
        val AD_MARKER = Regex("""\b(?:Sponsored|Promoted|Ad)\b""")
        val AI_MARKER = Regex("""AI[- ]generated""", RegexOption.IGNORE_CASE)

        const val CAPTION_MIN_LENGTH = 12
        val FEEDS = setOf("For You", "Following", "Friends", "Explore", "LIVE")
    }

    override fun shouldSkip(nodes: List<FlatNode>): Boolean =
        NodeTools.anyMatches(nodes, COMMENT_SHEET)

    override fun parse(nodes: List<FlatNode>): ParsedPost? {
        val post = ParsedPost(
            platform = platform,
            authorHandle = NodeTools.firstGroup(nodes, AUTHOR)
                ?: NodeTools.byViewId(nodes, "title", "author_name")?.text,
            caption = caption(nodes),
            music = NodeTools.byViewId(nodes, "music_title", "desc_music")?.text,
            feed = nodes.firstOrNull { it.text in FEEDS }?.text,
            likeRaw = NodeTools.firstGroup(nodes, LIKE),
            commentRaw = NodeTools.firstGroup(nodes, COMMENT),
            shareRaw = NodeTools.firstGroup(nodes, SHARE),
            saveRaw = NodeTools.firstGroup(nodes, SAVE),
            isAd = NodeTools.anyMatches(nodes, AD_MARKER),
            isAiGenerated = NodeTools.anyMatches(nodes, AI_MARKER),
        )
        return post.takeIf { it.isUsable() }
    }

    /**
     * The caption carries no stable view id, so it is identified by
     * shape: a long run of text with no contentDescription. The
     * comment-sheet guard above is what keeps a long comment from
     * matching this same shape.
     */
    private fun caption(nodes: List<FlatNode>): String? =
        NodeTools.byViewId(nodes, "desc", "video_desc")?.text
            ?: nodes.firstOrNull { node ->
                node.description == null &&
                    (node.text?.length ?: 0) >= CAPTION_MIN_LENGTH &&
                    node.text !in FEEDS
            }?.text
}

package edu.wellesley.scraper.parser

/**
 * Douyin (mainland build), Chinese UI.
 *
 * Douyin's action buttons are labelled in Chinese and counts are
 * abbreviated with 万/亿 rather than K/M, so none of TikTok's English
 * patterns apply -- hence a separate implementation rather than a
 * locale switch inside [TikTokParser].
 *
 * Unlike the TikTok selectors, these have NOT been checked against a
 * working collector. Treat every constant below as a hypothesis until
 * you have confirmed it against a `uiautomator dump`; see
 * docs/SELECTORS.md.
 */
class DouyinParser : PostParser {

    override val platform: String = "douyin"

    private companion object {
        // Both orderings appear across builds: "点赞12.3万" and "12.3万次点赞".
        val LIKE = Regex("""(?:点赞|喜欢)\s*([\d.]+\s*[万亿]?)|([\d.]+\s*[万亿]?)\s*(?:次)?点赞""")
        val COMMENT = Regex("""评论\s*([\d.]+\s*[万亿]?)|([\d.]+\s*[万亿]?)\s*(?:条)?评论""")
        val SHARE = Regex("""(?:分享|转发)\s*([\d.]+\s*[万亿]?)|([\d.]+\s*[万亿]?)\s*(?:次)?(?:分享|转发)""")
        val SAVE = Regex("""收藏\s*([\d.]+\s*[万亿]?)|([\d.]+\s*[万亿]?)\s*(?:次)?收藏""")

        /**
         * Anchored, so an @-mention inside a caption cannot be taken
         * for the author. Douyin renders the author label as its own
         * node.
         */
        val AUTHOR = Regex("""^@\s*([^\s，,。]{1,40})$""")

        /**
         * Douyin's stable account identifier is the 抖音号, which the
         * feed does not show -- it lives on the profile page. Captured
         * when it happens to be on screen, since it is what makes an
         * account findable later.
         */
        val DOUYIN_ID = Regex("""抖音号[：:\s]*([A-Za-z0-9._\-]{2,30})""")

        /**
         * Publication time, which Douyin renders and TikTok does not.
         *
         * Two forms sit on the same node: the contentDescription reads
         * `发布时间：17小时前` and the text reads `· 17小时前`. The
         * description is preferred because it is labelled -- the text
         * form is a bare relative time behind a separator, which could
         * be anything.
         *
         * Worth having even though an id decodes to the second. It is
         * the only reading independent of the id, so it is what a check
         * of the id arithmetic compares against; a first attempt at
         * that check had to compare two different videos, because this
         * was not being captured. It is also the only publication time
         * available at all for a post whose link was never copied,
         * which on this platform is most of them.
         */
        val POSTED_AT = Regex("""发布时间[：:]\s*(.+)""")
        val POSTED_AT_TEXT = Regex("""^[·•]\s*(\d+\s*(?:分钟|小时|天|周|个月|年)前|[\d\-年月日\s]{3,20})$""")
        val MUSIC = Regex("""@?(.+?)创作的原声|原声[：: ]\s*(.+)""")

        /**
         * Narrow markers of an open comment sheet, each named so a skip
         * says which fired. "条评论" is deliberately absent: it also
         * appears on the feed's own comment button, and the TikTok side
         * lost three quarters of a session to exactly that mistake.
         */
        val COMMENT_SHEET_MARKERS = listOf(
            "comment box" to Regex("""留下你的精彩评论|善语结善缘"""),
            "all comments header" to Regex("""^全部评论"""),
            "reply target" to Regex("""回复\s*@"""),
        )
        val AD_MARKER = Regex("""(?:广告|推广|品牌合作)""")
        val AI_MARKER = Regex("""(?:AI生成|AI创作|疑似AI)""")

        const val POST_CONTAINER = "video_container"
        const val CAPTION_MIN_LENGTH = 8

        val FEEDS = setOf("推荐", "关注", "朋友", "同城", "热点")
        val FEED_SLUGS = mapOf(
            "推荐" to "recommend",
            "关注" to "following",
            "朋友" to "friends",
            "同城" to "nearby",
            "热点" to "trending",
        )
    }

    override fun isPostBoundary(node: FlatNode): Boolean =
        node.viewId?.contains(POST_CONTAINER) == true

    /** Same fallback as TikTok: one visible tab label is the active one. */
    override fun feed(nodes: List<FlatNode>): String? {
        val selected = nodes.firstOrNull { it.selected && labelOf(it) != null }?.let(::labelOf)
        if (selected != null) return FEED_SLUGS[selected] ?: selected

        val only = nodes.mapNotNull(::labelOf).distinct().singleOrNull() ?: return null
        return FEED_SLUGS[only] ?: only
    }

    private fun labelOf(node: FlatNode): String? =
        node.text?.takeIf { it in FEEDS } ?: node.description?.takeIf { it in FEEDS }

    override fun skipReason(nodes: List<FlatNode>): String? =
        COMMENT_SHEET_MARKERS.firstOrNull { (_, pattern) ->
            NodeTools.anyMatches(nodes, pattern)
        }?.let { (name, _) -> "comment sheet open ($name)" }

    override fun parse(nodes: List<FlatNode>): ParsedPost? {
        val post = ParsedPost(
            platform = platform,
            authorHandle = NodeTools.firstGroup(nodes, DOUYIN_ID),
            authorName = NodeTools.firstGroup(nodes, AUTHOR)
                ?: NodeTools.byViewId(nodes, "author_name", "nickname", "title")?.text,
            caption = caption(nodes),
            postedAtRaw = NodeTools.firstGroup(nodes, POSTED_AT)
                ?: NodeTools.firstGroup(nodes, POSTED_AT_TEXT),
            music = NodeTools.firstGroup(nodes, MUSIC)
                ?: NodeTools.byViewId(nodes, "music_title")?.text,
            likeRaw = firstCount(nodes, LIKE),
            commentRaw = firstCount(nodes, COMMENT),
            shareRaw = firstCount(nodes, SHARE),
            saveRaw = firstCount(nodes, SAVE),
            isAd = NodeTools.anyMatches(nodes, AD_MARKER),
            isAiGenerated = NodeTools.anyMatches(nodes, AI_MARKER),
            videoIdHint = IdScanner.bestId(nodes),
        )
        return post.takeIf { it.isUsable() }
    }

    /** These patterns have two alternative capture groups; take whichever matched. */
    private fun firstCount(nodes: List<FlatNode>, pattern: Regex): String? {
        for (node in nodes) {
            for (candidate in listOfNotNull(node.description, node.text)) {
                val match = pattern.find(candidate) ?: continue
                val value = match.groupValues.drop(1).firstOrNull { it.isNotBlank() }
                if (value != null) return value.replace(" ", "")
            }
        }
        return null
    }

    private fun caption(nodes: List<FlatNode>): String? {
        NodeTools.byViewId(nodes, "desc")?.text?.let { return it }
        return nodes
            .filter {
                it.description == null &&
                    (it.text?.length ?: 0) >= CAPTION_MIN_LENGTH &&
                    it.text !in FEEDS
            }
            .maxByOrNull { it.text!!.length }
            ?.text
    }
}

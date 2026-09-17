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

        val AUTHOR = Regex("""@\s*([^\s，,。]+)""")
        val MUSIC = Regex("""@?(.+?)创作的原声|原声[：: ]\s*(.+)""")

        val COMMENT_SHEET = Regex("""(?:留下你的精彩评论|说点什么|全部评论|条评论)""")
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

    override fun feed(nodes: List<FlatNode>): String? {
        val label = nodes.firstOrNull { it.selected && it.text in FEEDS }?.text
            ?: nodes.firstOrNull { it.selected && it.description in FEEDS }?.description
        return FEED_SLUGS[label] ?: label
    }

    override fun shouldSkip(nodes: List<FlatNode>): Boolean =
        NodeTools.anyMatches(nodes, COMMENT_SHEET)

    override fun parse(nodes: List<FlatNode>): ParsedPost? {
        val post = ParsedPost(
            platform = platform,
            authorHandle = NodeTools.firstGroup(nodes, AUTHOR)
                ?: NodeTools.byViewId(nodes, "author_name", "nickname", "title")?.text,
            caption = caption(nodes),
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

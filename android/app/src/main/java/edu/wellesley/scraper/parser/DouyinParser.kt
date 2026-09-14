package edu.wellesley.scraper.parser

/**
 * Douyin (mainland build), Chinese UI.
 *
 * Douyin's action buttons are labelled in Chinese and the counts are
 * abbreviated with 万/亿 rather than K/M. None of TikTok's English
 * patterns apply, which is why this is a separate implementation
 * rather than a locale switch inside [TikTokParser].
 */
class DouyinParser : PostParser {

    override val platform: String = "douyin"

    private companion object {
        // "点赞12.3万" / "12.3万次点赞" -- both orderings appear across builds.
        val LIKE = Regex("""(?:点赞|喜欢)\s*([\d.]+\s*[万亿]?)|([\d.]+\s*[万亿]?)\s*(?:次)?点赞""")
        val COMMENT = Regex("""评论\s*([\d.]+\s*[万亿]?)|([\d.]+\s*[万亿]?)\s*(?:条)?评论""")
        val SHARE = Regex("""(?:分享|转发)\s*([\d.]+\s*[万亿]?)|([\d.]+\s*[万亿]?)\s*(?:次)?(?:分享|转发)""")
        val SAVE = Regex("""收藏\s*([\d.]+\s*[万亿]?)|([\d.]+\s*[万亿]?)\s*(?:次)?收藏""")
        val AUTHOR = Regex("""@\s*([^\s，,。]+)""")

        val COMMENT_SHEET = Regex("""(?:留下你的精彩评论|说点什么|条评论\s*$|全部评论)""")
        val AD_MARKER = Regex("""(?:广告|推广|品牌合作)""")
        val AI_MARKER = Regex("""(?:AI生成|AI创作|疑似AI)""")

        const val CAPTION_MIN_LENGTH = 8
        val FEEDS = setOf("推荐", "关注", "朋友", "同城", "热点")
    }

    override fun shouldSkip(nodes: List<FlatNode>): Boolean =
        NodeTools.anyMatches(nodes, COMMENT_SHEET)

    override fun parse(nodes: List<FlatNode>): ParsedPost? {
        val post = ParsedPost(
            platform = platform,
            authorHandle = NodeTools.firstGroup(nodes, AUTHOR)
                ?: NodeTools.byViewId(nodes, "author_name", "nickname", "title")?.text,
            caption = caption(nodes),
            music = NodeTools.byViewId(nodes, "music_title", "iv0")?.text,
            feed = nodes.firstOrNull { it.text in FEEDS }?.text,
            likeRaw = firstCount(nodes, LIKE),
            commentRaw = firstCount(nodes, COMMENT),
            shareRaw = firstCount(nodes, SHARE),
            saveRaw = firstCount(nodes, SAVE),
            isAd = NodeTools.anyMatches(nodes, AD_MARKER),
            isAiGenerated = NodeTools.anyMatches(nodes, AI_MARKER),
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

    private fun caption(nodes: List<FlatNode>): String? =
        NodeTools.byViewId(nodes, "desc", "video_desc", "tv_desc")?.text
            ?: nodes.firstOrNull { node ->
                node.description == null &&
                    (node.text?.length ?: 0) >= CAPTION_MIN_LENGTH &&
                    node.text !in FEEDS
            }?.text
}

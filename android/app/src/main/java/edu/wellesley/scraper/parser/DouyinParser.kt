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
         *
         * When it is not, the `@名字` beside the video is used as the
         * handle instead. That is the identifier on this platform in
         * practice: it is what the feed shows, what search accepts and
         * what someone would be contacted through. It is a nickname
         * and can be changed or shared with another account, so it is
         * weaker than TikTok's `@handle` -- but an empty column is not
         * the more honest answer, it is just an emptier one. The video
         * link remains the identifier that cannot drift.
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
        /**
         * Chrome that is not a post, and was being stored as one.
         *
         * The share sheet and the comment input bar each produced rows
         * in the corpus -- captions of 链接已复制成功，去粘贴分享： and
         * 爱评论的人，运气不会差, with no author and no counts, sitting
         * beside real videos. They got there because a segment with no
         * `desc` node falls back to its longest text, and on those
         * frames the longest text is the interface talking.
         *
         * The placeholder in the comment bar is written fresh for
         * different posts (期待你的评论, 有爱评论，说点儿好听的,
         * 爱评论的人，运气不会差), so the shape is matched rather than the
         * wording: a sentence about commenting, with no author beside it.
         */
        val UI_CHROME = Regex(
            """^(?:[链連鏈]接已复制|分享给|分享給|去粘[贴貼]分享|取消|""" +
                """[全屏]{2}[观觀]看|玩同款|同款特效|展开|展開|相[关關]搜索)""" +
                """|评论[的人]|[说說]点儿好听|你的[评評][论論]"""
        )

        val COMMENT_SHEET_MARKERS = listOf(
            "comment box" to Regex("""留下你的精彩评论|善语结善缘"""),
            "all comments header" to Regex("""^全部评论"""),
            "reply target" to Regex("""回复\s*@"""),
            // This panel got through all three and a comment was
            // stored as a video: name=优乐美, caption=[舔屏][舔屏][舔屏]女神 首评.
            // These three are unmistakable -- a feed has no enlarge
            // control, no downvote, and no numbered comment header.
            "enlarge control" to Regex("""放大[评評][论論]区"""),
            "vote controls" to Regex("""[踩赞]\\d*[,，]未[选選]中"""),
            "comment count header" to Regex("""^[评評][论論]\s*\d+$"""),
        )
        val SHARE_SHEET_OPEN = Regex("""^(?:分享给|分享給|[链連鏈]接已复制|去粘[贴貼]分享)""")

        /**
         * A profile page over the feed, which is not a post either.
         *
         * Both windows flatten into one frame while a profile is open,
         * and the 抖音号 on the profile then sits inside whichever feed
         * segment came last. A real run stored `handle=zz272328` on a
         * post by Devil: the id belongs to zz7, whose profile happened
         * to be on screen. The feed never shows a 抖音号, so its
         * presence is itself the signal that this frame is not a feed.
         */
        val PROFILE_OPEN = Regex("""抖音号|抖音號|复制名字|複製名字""")

        val AD_MARKER = Regex("""(?:广告|推广|品牌合作)""")
        val AI_MARKER = Regex("""(?:AI生成|AI创作|疑似AI)""")

        /**
         * Where one post ends and the next begins.
         *
         * `video_container` was a guess and does not exist in any dump
         * from the study phone, and a boundary that never matches does
         * not fail loudly: `NodeTools.segment` returns the whole frame
         * as a single segment, so every frame yielded exactly one post
         * assembled from the first matching node of each kind anywhere
         * on screen. With two or three videos in the tree at once that
         * pairs one video's author with another's caption. Two rows in
         * the first Douyin corpus carried the same caption, likes,
         * comments and shares under different display names -- one
         * video, stored twice, attributed to two people, neither
         * necessarily right.
         *
         * `user_avatar` is the repeating anchor in every dump taken so
         * far: one per post, first of the post's nodes after 关注. It
         * is also a name rather than an obfuscated id like `j+w` or
         * `z4_`, so it stands a better chance of surviving an update.
         * `video_container` is kept in case a build does use it.
         */
        val POST_CONTAINERS = arrayOf("user_avatar", "video_container")
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

    override fun isPostBoundary(node: FlatNode): Boolean {
        val id = node.viewId ?: return false
        return POST_CONTAINERS.any { id.contains(it) }
    }

    /** Same fallback as TikTok: one visible tab label is the active one. */
    override fun feed(nodes: List<FlatNode>): String? {
        val selected = nodes.firstOrNull { it.selected && labelOf(it) != null }?.let(::labelOf)
        if (selected != null) return FEED_SLUGS[selected] ?: selected

        val only = nodes.mapNotNull(::labelOf).distinct().singleOrNull() ?: return null
        return FEED_SLUGS[only] ?: only
    }

    private fun labelOf(node: FlatNode): String? =
        node.text?.takeIf { it in FEEDS } ?: node.description?.takeIf { it in FEEDS }

    override fun skipReason(nodes: List<FlatNode>): String? {
        // A frame with the share sheet over it is the sheet, not a
        // post. During an assisted run this is on screen for a second
        // of every video, which is how it ended up in the corpus.
        if (NodeTools.anyMatches(nodes, SHARE_SHEET_OPEN)) return "share sheet open"
        if (NodeTools.anyMatches(nodes, PROFILE_OPEN)) return "profile page open"
        // Many videos at once and no author beside any of them. Read
        // as a feed it became one row carrying one video's caption and
        // another's like count. Reading it properly is a separate job
        // -- see TikTokSearchParser for the shape that does it.
        if (nodes.any { it.viewId?.endsWith("et_search_kw") == true }) {
            return "search results page"
        }
        return COMMENT_SHEET_MARKERS.firstOrNull { (_, pattern) ->
            NodeTools.anyMatches(nodes, pattern)
        }?.let { (name, _) -> "comment sheet open ($name)" }
    }

    override fun parse(nodes: List<FlatNode>): ParsedPost? {
        val post = ParsedPost(
            platform = platform,
            authorHandle = NodeTools.firstGroup(nodes, DOUYIN_ID)
                ?: NodeTools.firstGroup(nodes, AUTHOR)
                ?: NodeTools.byViewId(nodes, "user_avatar")?.description,
            authorName = NodeTools.firstGroup(nodes, AUTHOR)
                ?: NodeTools.byViewId(nodes, "author_name", "nickname", "title")?.text
                // The avatar's contentDescription is the display name,
                // and it is the node most reliably present: `title`
                // renders a moment later, and a frame caught in between
                // had no author at all. Which is also what made a post
                // with no caption yet indistinguishable from interface
                // text -- neither had an author on it.
                ?: NodeTools.byViewId(nodes, "user_avatar")?.description,
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
        return post.takeIf { it.isUsable() && isAPost(post) }
    }

    /**
     * Whether this segment is a video rather than a piece of interface.
     *
     * Every real post in every dump carries an author beside it -- the
     * avatar's contentDescription and the `title` node both name one --
     * and almost all carry a count. Chrome carries neither: rows
     * captioned 发条评论，说说你的感受 and 未注册的手机号验证通过后将自动注册
     * reached the corpus with no author, no likes, no comments and no
     * shares, and then took a video id from a link paired by time.
     *
     * A structural test rather than more wording. Naming the strings is
     * the same losing game as naming the keyword collisions was: this
     * blocklist was written from four observed placeholders and two
     * more arrived in the next run, from a part of the interface --
     * a login prompt -- nobody had thought to list. What does not
     * change is that a video has an author.
     */
    private fun isAPost(post: ParsedPost): Boolean {
        if (!post.authorName.isNullOrBlank() || !post.authorHandle.isNullOrBlank()) {
            return true
        }
        return post.likeRaw != null || post.commentRaw != null || post.shareRaw != null
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
        // The fallback is for a post whose caption node is missing, not
        // a licence to store whatever text is longest. Without the
        // UI_CHROME test it stored the share sheet and the comment bar.
        return nodes
            .filter {
                it.description == null &&
                    (it.text?.length ?: 0) >= CAPTION_MIN_LENGTH &&
                    it.text !in FEEDS &&
                    !UI_CHROME.containsMatchIn(it.text!!) &&
                    // The author line is the longest text on a frame
                    // whose caption has not rendered, so the fallback
                    // took it: a row went in reading
                    // caption=@咸鱼不闲（求推荐版）. A caption is stored
                    // verbatim and cannot be recomputed later, so a
                    // wrong one is permanent where an empty one is a
                    // gap the next frame fills.
                    !AUTHOR.containsMatchIn(it.text!!)
            }
            .maxByOrNull { it.text!!.length }
            ?.text
    }
}

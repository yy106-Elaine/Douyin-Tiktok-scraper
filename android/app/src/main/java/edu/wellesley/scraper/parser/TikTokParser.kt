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
        /**
         * The engagement labels, in both of TikTok's interface
         * languages.
         *
         * TikTok localises its accessibility descriptions, and this
         * parser was written against the English ones only. A run on
         * a phone whose TikTok was in Chinese therefore read captions
         * fine -- those come from a view id -- and returned null for
         * every count, every handle and every feed name, with nothing
         * in the output to say why. It also never found the share
         * control, so the run collected no links at all: 348 frames,
         * 0 links, stopped after 3 failures.
         *
         * So each label is matched in either language. The Chinese
         * builds separate the name from the count with a full-width
         * 。and count in 万/亿 rather than K/M/B ("点赞视频。2.7 万 个赞");
         * the count is kept as the displayed string either way and
         * `app/counts.py` reads both scales.
         */
        val COUNT = """([\d.,]+\s*[KMB万亿萬億]?)"""

        val LIKE = Regex("""(?:Like video\.\s*$COUNT\s*likes|点[赞讚]视频。\s*$COUNT\s*个[赞讚])""", RegexOption.IGNORE_CASE)
        val COMMENT = Regex(
            """(?:Read or add comments\.\s*$COUNT\s*comments|[阅閱][读讀]或添加[评評][论論]。\s*$COUNT\s*[条條][评評][论論])""",
            RegexOption.IGNORE_CASE,
        )
        val SHARE = Regex("""(?:Share video\.\s*$COUNT\s*shares|分享视频。\s*$COUNT\s*次分享)""", RegexOption.IGNORE_CASE)

        /**
         * Favourites count, where a build exposes one.
         *
         * This build does not. Its button reads "Add or remove this
         * video from Favorites." with no number anywhere in the
         * subtree, so save_count is simply unavailable -- see
         * docs/SELECTORS.md. The lookups are kept because they cost
         * nothing and other builds do label it, but do not expect this
         * column to fill.
         */
        val SAVE_MARKER = Regex(
            """(?:add to |remove from )?favou?rites?|bookmark|collect|[将將]此视频添加到或移出收藏|收藏""",
            RegexOption.IGNORE_CASE,
        )
        val SAVE_INLINE = Regex(
            """$COUNT\s*(?:favou?rites?|bookmarks?|次收藏|个收藏)""", RegexOption.IGNORE_CASE
        )

        /** "· 2025-05-31", and sometimes a relative form instead. */
        val POST_TIME_ID = "tv_post_time"

        /**
         * The in-app browser, open over the feed.
         *
         * Its page content flattens into the same tree, and a live
         * capture stored a shop's cookie banner as a video's caption.
         * The engagement counts on such a frame are still the video's,
         * so the frame is kept -- only the shape-based caption guess is
         * withheld, since that is what the overlay's text hijacks.
         */
        val BROWSER_URL = Regex("""^(?:https?://|www\.)[\w.\-]+""", RegexOption.IGNORE_CASE)
        val COUNT_SHAPED = Regex("""^\d{1,3}([.,]\d+)?\s*[KMB万亿萬億]?$""", RegexOption.IGNORE_CASE)

        /** "YUE profile" in English, "YUE 主页" in Chinese. */
        val AUTHOR = Regex("""(?:(.+?)\s+profile|(.+?)\s*主[页頁])""", RegexOption.IGNORE_CASE)

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
         * The comment bar's "mention someone" control is described as
         * `@<numeric user id>`, which a live capture stored as the
         * author's handle. A handle carries at least one letter; an
         * all-digit token is an internal id and is not one.
         */
        val HAS_A_LETTER = Regex("""[A-Za-z]""")

        /** "Follow SierraLocklear" -- another rendering of the name. */
        val FOLLOW = Regex("""^(?:Follow\s+(.+)|[关關]注\s*(.+))$""", RegexOption.IGNORE_CASE)

        /** Nodes belonging to the comment composer, not to the post. */
        val COMMENT_BAR_IDS = listOf("ed5", "kgq", "lcn", "lk6")

        /** "Search · wlw relationship moments" -- the sampling frame. */
        /**
         * The strip naming the search a video was opened from.
         *
         * This is the only place a TikTok row records which keyword
         * produced it, and on TikTok the keyword is the sample
         * definition -- see docs/METHODOLOGY.md -- so losing it to a
         * language setting loses more than a label.
         */
        val SEARCH_CONTEXT = Regex("""^(?:Search|搜索|搜尋)\s*[·・]\s*(.+)$""")

        /**
         * The caption TextView also renders the "expand" affordance, so
         * the text arrives as "<caption> more" or "<caption>...more".
         * Left in place it adds a meaningless token to every caption,
         * which matters for text analysis. The trade-off is a caption
         * genuinely ending in the word "more" losing that word; carrying
         * a UI control into the data is the worse of the two.
         */
        val TRAILING_EXPAND = Regex("""\s*(?:\.{3}|…)?\s*more\s*$""", RegexOption.IGNORE_CASE)
        /** "Sound: X", "音乐：X", and "X 创作的原声" the other way round. */
        val MUSIC = Regex(
            """(?:Sound:\s*(.+)|音[乐樂][：:]\s*(.+)|(.+?)\s*[创創]作的原[声聲])""",
            RegexOption.IGNORE_CASE,
        )

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
        /**
         * Wording that only the share sheet has.
         *
         * Matched on entries that are unmistakably the sheet's --
         * its title, its container, and the actions it alone offers.
         * 复制链接 is deliberately not here: it is what the run is
         * there to press.
         */
        val SHARE_SHEET_OPEN =
            Regex("""^(?:[发發]送[给給]|底部工作表|[邀][请請]好友聊天|添加到限[时時][动動][态態]|[创創]建群[组組]|拼接)$""")

        val AD_MARKER = Regex("""(?:paid partnership|sponsored|promoted)""", RegexOption.IGNORE_CASE)
        val AI_MARKER = Regex("""AI[- ]generated""", RegexOption.IGNORE_CASE)

        /**
         * Markers for the root of one post.
         *
         * A live frame held two videos, each opening with
         * `long_press_layout`, and `widget_container` was absent
         * entirely -- so the whole tree was read as a single post and
         * the two videos' fields were merged into one row. Both are
         * accepted, since builds differ.
         */
        val POST_CONTAINERS = arrayOf("long_press_layout", "widget_container")

        /** Below this length a stray label is more likely than a caption. */
        const val CAPTION_MIN_LENGTH = 30

        /** Guard against stripping a short caption into uselessness. */
        const val MIN_STRIPPED_LENGTH = 3

        val FEEDS = setOf(
            "For You", "Following", "Friends", "Explore", "Shop", "LIVE",
            "推荐", "推薦", "关注", "關注", "朋友", "探索", "商城", "直播",
        )
        val FEED_SLUGS = mapOf(
            "For You" to "recommend",
            "Following" to "following",
            "Friends" to "friends",
            "Explore" to "explore",
            "Shop" to "shop",
            "LIVE" to "live",
        )
    }

    override fun isPostBoundary(node: FlatNode): Boolean {
        val id = node.viewId ?: return false
        return POST_CONTAINERS.any { id.contains(it) }
    }

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
        // Browsing search results shows the query on screen; that is
        // the sampling frame, and it outranks any tab label.
        NodeTools.firstGroup(nodes, SEARCH_CONTEXT)?.let { return "search:${it.trim()}" }

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

    override fun skipReason(nodes: List<FlatNode>): String? {
        // The share sheet covers the feed, and it is not a post. Read
        // as one it stored seven rows whose author was 发送给 -- the
        // sheet's own title, which arrives under a `tv_title` view id
        // and so answered the lookup for the display name. Douyin's
        // parser has had this guard since its own sheet did the same.
        if (NodeTools.anyMatches(nodes, SHARE_SHEET_OPEN)) return "share sheet open"
        return COMMENT_SHEET_MARKERS.firstOrNull { (_, pattern) ->
            NodeTools.anyMatches(nodes, pattern)
        }?.let { (name, _) -> "comment sheet open ($name)" }
    }

    override fun parse(nodes: List<FlatNode>): ParsedPost? {
        val post = ParsedPost(
            platform = platform,
            authorHandle = handle(nodes),
            authorName = displayName(nodes),
            caption = caption(nodes),
            postedAtRaw = NodeTools.byViewId(nodes, POST_TIME_ID)?.text
                ?.removePrefix("·")?.trim(),
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
            if (node.viewId?.let { id -> COMMENT_BAR_IDS.any(id::contains) } == true) continue
            for (candidate in listOfNotNull(node.text, node.description)) {
                val found = HANDLE_ONLY.find(candidate.trim())?.groupValues?.get(1)
                if (found != null && HAS_A_LETTER.containsMatchIn(found)) return found
            }
        }
        // Some builds put the handle in the profile label instead.
        val label = NodeTools.firstGroup(nodes, AUTHOR)?.trim()
        return label?.removePrefix("@")?.takeIf { label.startsWith("@") }
    }

    private fun displayName(nodes: List<FlatNode>): String? =
        NodeTools.firstGroup(nodes, AUTHOR)?.removePrefix("@")?.trim()
            ?: NodeTools.byViewId(nodes, "title")?.text
            // "Follow SierraLocklear" -- present even when the profile
            // label is not.
            ?: NodeTools.firstGroup(nodes, FOLLOW)?.trim()

    /**
     * The caption has a view id on some builds and none on others, so
     * it falls back to shape: the longest undescribed run of text. The
     * comment-sheet guard is what keeps a long comment from matching
     * that same shape.
     */
    private fun caption(nodes: List<FlatNode>): String? {
        NodeTools.byViewId(nodes, "desc")?.text?.let { return stripExpandAffordance(it) }

        // With the in-app browser open, the longest undescribed text on
        // screen belongs to a web page, not to the video.
        if (NodeTools.anyMatches(nodes, BROWSER_URL)) return null

        val raw = nodes
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

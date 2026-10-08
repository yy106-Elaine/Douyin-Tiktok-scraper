package edu.wellesley.scraper.service

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Douyin's search results grid, read as a list of posts to open.
 *
 * The video loop collects from a feed: one post fills the screen, and
 * the next one is a swipe away. 图文 posts have no such feed. They
 * arrive as cells in the results grid, and the only way to a post's
 * share control is to open the post, copy, and come back out -- which
 * is exactly what was being done by hand for every note in this
 * corpus.
 *
 * So this is the other surface's equivalent of "the next video": the
 * next cell that has not been opened yet.
 *
 * **Identified by its own text, not by its position.** An index into
 * the grid is wrong as soon as the grid moves, and it moves for
 * reasons outside this app: the list loads more rows, a cell resizes
 * once its thumbnail arrives, and coming back from a post does not
 * always restore the same scroll offset. Opening the fourth cell
 * twice and never opening the fifth is a silent failure -- the run
 * looks fine and collects half of what it claims. A cell's label is
 * the post's own title, so it survives all of that.
 *
 * **Nothing here presses anything**, for the same reason as
 * [ShareSheet]: the dry run is the same search without the tap, so
 * the selectors can be checked against a real screen first. No wording
 * on this surface has ever been dumped from a device.
 */
object SearchGrid {

    /**
     * Labels that belong to the page rather than to a post.
     *
     * The search box, the results tabs and the cancel button are all
     * clickable and all carry text, so without this the first thing a
     * run would "open" is the 综合 tab -- and tapping a tab reloads
     * the grid underneath it, which loses the place and collects
     * nothing.
     */
    private val CHROME = listOf(
        // Read off a real grid. Douyin marks every control in the
        // accessibility tree with 按钮, and the first dry run offered
        // "未点赞，喜欢，按钮" as a cell to open -- the like button on
        // a card. Tapping that is an action on somebody's account,
        // which is the one thing this must never do.
        Regex("""[，,]\s*按钮$"""),
        Regex("""^(未)?[点點]?[赞贊]|^喜[欢歡]$|^收藏$|^[评評][论論]$"""),
        // A card's age. The digits are gone by the time this is read
        // (see fingerprint), so "3小时前" arrives as "小时前".
        Regex("""^(秒|分[钟鐘]|小[时時]|天|周|[个個]?月|年)前$"""),
        Regex("""^(刚刚|剛剛|昨天|前天)$"""),
        Regex("""^(综合|綜合|视频|視頻|用户|用戶|直播|商品|音乐|音樂|图文|圖文)$"""),
        Regex("""^(取消|搜索|搜尋|返回|清除|cancel|search|back)$""", RegexOption.IGNORE_CASE),
        Regex("""^(筛选|篩選|排序|最多点赞|最新发布|综合排序)"""),
        // The search box itself, whose text is the query that was typed.
        Regex("""^搜索[:：]"""),
    )

    /**
     * One result cell: what to tap, what it calls itself, and how big
     * it is. The size is carried so a dry run can print it -- the
     * thresholds below were set from one screen, and the next screen
     * that disagrees should be able to say so in numbers.
     */
    data class Tile(
        val node: AccessibilityNodeInfo,
        val label: String,
        val width: Int = 0,
        val height: Int = 0,
    )

    /**
     * The results page's own tab strip. One of these is pinned at the
     * top of the grid and none of them is on a post.
     */
    private val RESULT_TABS = listOf(
        Regex("""^(综合|綜合)$"""),
        Regex("""^(视频|視頻)$"""),
        Regex("""^(用户|用戶)$"""),
        Regex("""^(图文|圖文)$"""),
        Regex("""^(筛选|篩選)"""),
        Regex("""^(清空|最多点赞|最新发布|综合排序)$"""),
    )

    /**
     * Whether the results grid is the screen in front -- on positive
     * evidence, not on the absence of anything.
     *
     * This asked [ShareSheet.isSearchResults], which looks for the
     * search box. That is the right question for a feed run, where
     * the search box means "you have wandered off the feed, stop".
     * It is the wrong one here, and the difference did damage: a post
     * opened out of the results keeps the search box in its window
     * tree, so the post read as the grid. A run that had failed to
     * find the share control went back, believed it was home, and
     * tapped the largest labelled thing on the post -- which on a 图文
     * is the like area. It liked somebody's post, which is the one
     * class of action this app must never take.
     *
     * So: the page's own tab strip has to be there, AND at least two
     * cards, which a post page does not have. Being wrong the other
     * way costs a stopped run and a line in the log.
     */
    fun isGrid(
        roots: List<AccessibilityNodeInfo>,
        screenWidth: Int,
        screenHeight: Int,
    ): Boolean {
        if (!ShareSheet.isSearchResults(roots)) return false
        if (!hasTabStrip(roots)) return false
        return isGridEvidence(
            searchBox = true,
            tabStrip = true,
            cards = tiles(roots, screenWidth, screenHeight).size,
        )
    }

    /**
     * The rule itself, apart from the screen, so it can be tested.
     *
     * All three, every time. Each one alone is true of a post opened
     * out of the results: it carries the search box, it can carry a
     * strip, and it has large labelled regions. Only the grid has two
     * cards side by side.
     */
    fun isGridEvidence(searchBox: Boolean, tabStrip: Boolean, cards: Int): Boolean =
        searchBox && tabStrip && cards >= MIN_CARDS

    /** Whether the results page's tab strip is on screen. */
    fun hasTabStrip(roots: List<AccessibilityNodeInfo>): Boolean {
        for (root in roots) {
            var seen = false
            walk(root) { node ->
                val text = labelOf(node)?.trim()
                if (text != null && RESULT_TABS.any { it.containsMatchIn(text) }) {
                    seen = true
                    false
                } else {
                    true
                }
            }
            if (seen) return true
        }
        return false
    }

    /**
     * The cells that can be opened, in reading order.
     *
     * Reading order because that is the order a person would go in,
     * and because it makes "where did the run get to" answerable from
     * the log. A cell is a clickable node carrying text of its own,
     * wholly on screen, below the search bar and the tabs.
     *
     * @param screenHeight pixels; the top band is the page's own chrome
     */
    fun tiles(
        roots: List<AccessibilityNodeInfo>,
        screenWidth: Int,
        screenHeight: Int,
        onReject: ((String) -> Unit)? = null,
    ): List<Tile> {
        val bounds = Rect()
        // Keyed by the card that would be tapped, not by the text.
        // A card carries a title and an author name, and both are
        // labels on the same clickable card: the first live run read
        // them as two cells, opened the same post twice and spent a
        // third of its budget on it. Where one card offers several
        // labels the longest wins, which is the title -- an author
        // name is the same on every post they have.
        val byCard = LinkedHashMap<String, Triple<Int, Int, Tile>>()
        for (root in roots) {
            walk(root) { node ->
                val raw = labelOf(node) ?: return@walk true
                val text = fingerprint(raw)
                if (text.isEmpty()) return@walk true
                if (!isPostLabel(text)) {
                    onReject?.invoke("not a post: $text")
                    return@walk true
                }
                val target = clickableSelfOrAncestor(node) ?: run {
                    onReject?.invoke("nothing tappable around: $text")
                    null
                } ?: return@walk true
                target.getBoundsInScreen(bounds)
                val belowChrome = bounds.top > screenHeight * TOP_BAND
                val onScreen = bounds.bottom <= screenHeight && bounds.top >= 0
                if (!belowChrome || !onScreen) {
                    // With the box, because this is the rejection that
                    // cannot be reasoned about from a label. The
                    // clickable ancestor of a title is sometimes the
                    // card and sometimes the whole scrolling list, and
                    // those two look identical in a dump of names --
                    // they differ only in how tall the box is.
                    onReject?.invoke(
                        "off the grid area (top=${bounds.top} " +
                            "bottom=${bounds.bottom} of $screenHeight, " +
                            "chrome ends at ${(screenHeight * TOP_BAND).toInt()}" +
                            "): $text",
                    )
                    return@walk true
                }
                if (!isCardSized(
                        bounds.width(), bounds.height(), screenWidth, screenHeight,
                    )
                ) {
                    onReject?.invoke(
                        "too small (${bounds.width()}x${bounds.height()} " +
                            "of ${screenWidth}x$screenHeight): $text",
                    )
                    return@walk true
                }
                val card = "${bounds.left},${bounds.top}," +
                    "${bounds.right},${bounds.bottom}"
                val already = byCard[card]
                if (already == null || text.length > already.third.label.length) {
                    byCard[card] = Triple(
                        bounds.top,
                        bounds.left,
                        Tile(target, text, bounds.width(), bounds.height()),
                    )
                }
                true
            }
        }
        return byCard.values
            .sortedWith(compareBy({ it.first / ROW_TOLERANCE }, { it.second }))
            .map { it.third }
    }

    /**
     * Whether something this size can be a card.
     *
     * The wording checks are a list of what has been seen; this is
     * the rule that does not need to have seen it. A results card is
     * a column of the grid and most of a thumbnail tall. The first
     * dry run offered a like button and a timestamp as cells to open
     * -- both carry text, both are clickable, and both are a fraction
     * of this size. One of them likes somebody's post.
     */
    fun isCardSized(
        width: Int,
        height: Int,
        screenWidth: Int,
        screenHeight: Int,
    ): Boolean =
        width >= screenWidth * MIN_TILE_WIDTH &&
            height >= screenHeight * MIN_TILE_HEIGHT

    /**
     * Whether a label looks like a post rather than the page's own
     * furniture. Short labels are counts and badges ("1.2万", "广告").
     *
     * Anything [ShareSheet] recognises is a control, not a post, and
     * is refused here as well. The grid is a list of other people's
     * posts, and a label that reads 关注 or 建群分享 is an action on
     * somebody's account -- those are pinned out of the feed loop by
     * name, and a cell opener that chose what to tap by "it had text
     * and it was clickable" is exactly how one would get pressed
     * anyway.
     */
    fun isPostLabel(label: String): Boolean =
        label.length >= MIN_LABEL &&
            CHROME.none { it.containsMatchIn(label) } &&
            ShareSheet.roleOf(label) == null &&
            ACCOUNT_ACTIONS.none { it.containsMatchIn(label) }

    /**
     * One post's label, reduced to something comparable.
     *
     * The same cell reads back differently between visits, and the
     * difference is almost always a number: the like count ticks over
     * while the grid is open, and a cell that read 1.2万赞 on the way
     * in reads 1.3万赞 on the way back. A raw compare therefore sees a
     * new post, opens it again, and the run spends its deadline on
     * the top of the list.
     *
     * So the digits go, along with the magnitude characters that
     * carry them, and whitespace is collapsed. What is left is the
     * title, which is what identifies the post to a person too.
     *
     * The cost is that two posts with the same title are treated as
     * one, and the second is skipped. That is the right way round: a
     * post skipped is visible as a gap in the day's count, where a
     * post collected twice is invisible and inflates it.
     */
    fun fingerprint(label: String): String =
        label.replace(COUNTS, "")
            .trim()
            .replace(WHITESPACE, " ")
            .take(FINGERPRINT_CHARS)

    /**
     * The first cell not opened yet, or null if every one on screen
     * has been. Null is the signal to scroll, not to stop.
     */
    fun pick(labels: List<String>, done: Set<String>): Int? {
        labels.forEachIndexed { index, label ->
            if (fingerprint(label) !in done) return index
        }
        return null
    }

    /** What is on screen, for when nothing was found. */
    fun describe(roots: List<AccessibilityNodeInfo>, limit: Int = 30): List<String> =
        ShareSheet.describe(roots, limit)

    private fun labelOf(node: AccessibilityNodeInfo): String? {
        val description = node.contentDescription?.toString()?.trim()
        if (!description.isNullOrEmpty()) return description
        return node.text?.toString()?.trim()?.takeIf { it.isNotEmpty() }
    }

    private fun clickableSelfOrAncestor(
        node: AccessibilityNodeInfo,
    ): AccessibilityNodeInfo? {
        var current: AccessibilityNodeInfo? = node
        var depth = 0
        while (current != null && depth < 5) {
            if (current.isClickable) return current
            current = current.parent
            depth++
        }
        return null
    }

    private fun walk(
        root: AccessibilityNodeInfo?,
        visit: (AccessibilityNodeInfo) -> Boolean,
    ) {
        if (root == null) return
        val queue = ArrayDeque<Pair<AccessibilityNodeInfo, Int>>()
        queue.add(root to 0)
        var seen = 0
        while (queue.isNotEmpty() && seen < MAX_NODES) {
            val (node, depth) = queue.removeFirst()
            seen++
            if (!visit(node)) return
            if (depth >= MAX_DEPTH) continue
            for (index in 0 until node.childCount) {
                queue.add((node.getChild(index) ?: continue) to depth + 1)
            }
        }
    }

    private val WHITESPACE = Regex("""\s+""")

    /**
     * Actions on someone else's account. Never a post, never tapped.
     *
     * The same list the feed loop is pinned against by test. It is
     * repeated here rather than referenced because the two surfaces
     * fail differently: there the risk is a control mistaken for the
     * share button, here it is a control mistaken for a post.
     */
    private val ACCOUNT_ACTIONS = listOf(
        Regex("""^(关注|關注|follow)$""", RegexOption.IGNORE_CASE),
        Regex("""建群分享|合拍|拼接|举报|舉報|推荐|推薦|转发|轉發|日常|限时动态|创建群组|下载|下載"""),
    )

    /** Digits and the characters that scale them: 1.2万, 3.4亿, 567. */
    private val COUNTS = Regex("""[0-9.]+\s*[万億亿]?""")

    /** Below this fraction of the screen is the page's own chrome. */
    private const val TOP_BAND = 0.12

    /**
     * A card's smallest plausible share of the screen. Douyin's
     * results are two or three columns, so a third of the width is
     * already generous for the narrow case; the height keeps out the
     * single-line rows that sit under a card.
     */
    private const val MIN_TILE_WIDTH = 0.22
    private const val MIN_TILE_HEIGHT = 0.12

    /**
     * Cards that have to be on screen before this is a grid. Two,
     * because a post page can offer one large labelled region -- the
     * image, the caption -- and never offers two side by side.
     */
    private const val MIN_CARDS = 2

    /** Cells within this many pixels of each other are one row. */
    private const val ROW_TOLERANCE = 80

    /**
     * Shorter than this is a badge, not a title. Three rather than
     * four because 图文 titles are often very short (我和她), and the
     * badges that would otherwise slip through -- 广告, 直播, a bare
     * count once its digits are dropped -- are shorter still or are
     * named in [CHROME].
     */
    private const val MIN_LABEL = 3
    private const val FINGERPRINT_CHARS = 60
    private const val MAX_NODES = 900
    private const val MAX_DEPTH = 40
}

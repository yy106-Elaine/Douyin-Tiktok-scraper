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
        Regex("""^(综合|綜合|视频|視頻|用户|用戶|直播|商品|音乐|音樂|图文|圖文)$"""),
        Regex("""^(取消|搜索|搜尋|返回|清除|cancel|search|back)$""", RegexOption.IGNORE_CASE),
        Regex("""^(筛选|篩選|排序|最多点赞|最新发布|综合排序)"""),
        // The search box itself, whose text is the query that was typed.
        Regex("""^搜索[:：]"""),
    )

    /** One result cell: what to tap, and what it calls itself. */
    data class Tile(val node: AccessibilityNodeInfo, val label: String)

    /**
     * Whether the results grid is the screen in front.
     *
     * The same test [ShareSheet.isSearchResults] makes, and
     * deliberately the same one: there the grid means a video run has
     * wandered off its surface and must stop, here it means the run is
     * home. One definition, two readings.
     */
    fun isGrid(roots: List<AccessibilityNodeInfo>): Boolean =
        ShareSheet.isSearchResults(roots)

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
        screenHeight: Int,
    ): List<Tile> {
        val bounds = Rect()
        val found = mutableListOf<Triple<Int, Int, Tile>>()
        val seen = mutableSetOf<String>()
        for (root in roots) {
            walk(root) { node ->
                val text = labelOf(node)?.let { fingerprint(it) }
                if (text == null || !isPostLabel(text)) return@walk true
                val target = clickableSelfOrAncestor(node) ?: return@walk true
                target.getBoundsInScreen(bounds)
                val belowChrome = bounds.top > screenHeight * TOP_BAND
                val onScreen = bounds.bottom <= screenHeight && bounds.top >= 0
                if (belowChrome && onScreen && seen.add(text)) {
                    found.add(Triple(bounds.top, bounds.left, Tile(target, text)))
                }
                true
            }
        }
        return found
            .sortedWith(compareBy({ it.first / ROW_TOLERANCE }, { it.second }))
            .map { it.third }
    }

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

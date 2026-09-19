package edu.wellesley.scraper.service

import android.view.accessibility.AccessibilityNodeInfo

/**
 * Finds the two controls an assisted run has to press.
 *
 * The share control's wording is known from real dumps -- the same
 * string `TikTokParser` already reads the share count from. The share
 * sheet's "copy link" entry is not: no dump of an open sheet has been
 * taken, so every plausible wording is listed and the run records
 * which one matched. When none matches it says so and stops, rather
 * than pressing whatever else is nearby.
 *
 * Nothing here presses anything. It returns the node and lets the
 * caller decide, which is what makes a dry run possible: the same
 * search without the press, so the selectors can be checked on a real
 * screen before anything is tapped.
 *
 * Every search takes a list of window roots rather than one. A dry run
 * on Douyin reported both controls missing while the feed was plainly
 * on screen: `rootInActiveWindow` had returned the comment-input
 * overlay, a separate window holding three nodes, and the feed -- with
 * `分享，按钮` in it -- was in a window nobody looked at. One window is
 * not the screen.
 */
object ShareSheet {

    /**
     * How the share control identifies itself, in both apps.
     *
     * Anchored to the start of the label on purpose. A bare 分享
     * substring also appears in 建群分享 and 去粘贴分享, both entries
     * inside the sheet -- and 建群分享 creates a group chat, which is an
     * action on someone else's account and exactly what this must never
     * press. Douyin's own control reads 分享，按钮 and TikTok's reads
     * Share video, so the start of the label is enough.
     */
    private val SHARE = listOf(
        Regex("""^share video$""", RegexOption.IGNORE_CASE),
        Regex("""^share$""", RegexOption.IGNORE_CASE),
        // Whole label, not a prefix. `^分享` matched 分享你此刻的想法 --
        // the comment box's placeholder -- and a run tapped it, which
        // is how it ended up somewhere that has no share sheet and
        // then on the search results page. Douyin's control reads
        // 分享，按钮 or 分享8，按钮 with the count folded in.
        Regex("""^分享\d*(?:[，,]\s*按钮)?$"""),
    )

    /**
     * The entry inside the sheet that puts a link on the clipboard.
     *
     * Douyin calls it **分享链接**, not 复制链接 -- read off a real share
     * sheet. Only after it is pressed does anything say 复制: a toast
     * reading 链接已复制 and a second sheet headed 链接已复制成功. So the
     * word to match on is 链接, and matching on 复制 finds nothing until
     * the press has already happened.
     *
     * TikTok calls it **Copy link**.
     */
    private val COPY_LINK = listOf(
        Regex("""copy link""", RegexOption.IGNORE_CASE),
        Regex("""分享[链連鏈]接"""),
        Regex("""复制[链連鏈]接"""),
        Regex("""複製[鏈链連]接"""),
        Regex("""复制口令"""),
        Regex("""^copy$""", RegexOption.IGNORE_CASE),
    )

    /**
     * Wording that means a sheet is covering the feed.
     *
     * Douyin opens two in a row: 分享给 to pick a destination, then
     * 链接已复制成功，去粘贴分享 once the link is on the clipboard. Both
     * have to be gone before a swipe reaches the feed, and a swipe that
     * lands on an open sheet scrolls the sheet instead.
     */
    private val SHEET = listOf(
        Regex("""分享给"""),
        Regex("""分享給"""),
        Regex("""去粘贴分享"""),
        Regex("""[链連鏈]接已复制"""),
        Regex("""^send to$""", RegexOption.IGNORE_CASE),
        Regex("""^share to$""", RegexOption.IGNORE_CASE),
        // The comment panel belongs here for the same reason: it
        // covers the feed, so the share control underneath is not
        // reachable and a swipe scrolls comments. A run found itself
        // in one and pressed on regardless.
        Regex("""放大[评評][论論]区"""),
        Regex("""[踩赞]\\d*[,，]未[选選]中"""),
    )

    /** A node, and the label that matched, for the run's log. */
    data class Found(val node: AccessibilityNodeInfo, val label: String)

    /** What a label on screen means. */
    enum class Role { SHARE, COPY_LINK, SHEET, DISMISS }

    /**
     * The sheet's own way out.
     *
     * Tapped instead of the global BACK. BACK means whatever the
     * current screen decides it means: on a sheet it closes the sheet,
     * on a video it leaves the video, and from a video reached through
     * search it goes to the results and then to the search box -- all
     * of which happened. A named control can only do the one thing it
     * says, so there is nothing left to get wrong about where we are.
     */
    private val DISMISS = listOf(
        Regex("""^取消$"""),
        Regex("""^關閉$"""),
        Regex("""^关闭$"""),
        Regex("""^cancel$""", RegexOption.IGNORE_CASE),
        Regex("""^close$""", RegexOption.IGNORE_CASE),
    )

    /**
     * What a label means, decided on the text alone.
     *
     * Every wording question lives here, so it can be tested against
     * labels read off real share sheets without a device. Two builds
     * were spent guessing at these strings; a test is cheaper.
     *
     * Order is the exclusion. 分享链接, 分享给 and 去粘贴分享 all contain
     * 分享, and one of them -- 建群分享 -- would create a group chat if it
     * were ever mistaken for the share control. Copy first, then sheet
     * wording, and only what is left can be the control that opens a
     * sheet.
     */
    fun roleOf(label: String): Role? = when {
        COPY_LINK.any { it.containsMatchIn(label) } -> Role.COPY_LINK
        DISMISS.any { it.containsMatchIn(label) } -> Role.DISMISS
        SHEET.any { it.containsMatchIn(label) } -> Role.SHEET
        SHARE.any { it.containsMatchIn(label) } -> Role.SHARE
        else -> null
    }

    /** The sheet's cancel or close control, if it offers one. */
    fun findDismiss(roots: List<AccessibilityNodeInfo>): Found? =
        find(roots, Role.DISMISS)

    /**
     * The share control on the feed.
     *
     * Copy-link and sheet wording lose to [roleOf]'s ordering, so a
     * search run while a sheet is open cannot return one of the sheet's
     * own entries and press it believing a sheet had just been opened.
     */
    fun findShare(roots: List<AccessibilityNodeInfo>): Found? = find(roots, Role.SHARE)

    fun findCopyLink(roots: List<AccessibilityNodeInfo>): Found? =
        find(roots, Role.COPY_LINK)

    /**
     * Whether the screen is Douyin's search results rather than a feed.
     *
     * A run that ends up here keeps swiping a grid that has no share
     * control, which is not collection and is not where anything
     * should be pressed. It is a surface with its own shape -- many
     * videos at once, no author beside any of them -- and reading it
     * properly is a separate job from this loop.
     */
    fun isSearchResults(roots: List<AccessibilityNodeInfo>): Boolean {
        for (root in roots) {
            var found = false
            walk(root) { node ->
                if (node.viewIdResourceName?.endsWith("et_search_kw") == true) {
                    found = true
                    false
                } else {
                    true
                }
            }
            if (found) return true
        }
        return false
    }

    /** Whether a share sheet is covering the feed; see [SHEET]. */
    fun isSheetOpen(roots: List<AccessibilityNodeInfo>): Boolean =
        find(roots, Role.SHEET, matchUnclickable = true) != null

    /**
     * What is on screen, for when a search failed.
     *
     * A run that cannot find its control is the expected failure --
     * the wording differs by app version and by language -- so the
     * useful thing is a list of what was there instead. This is what
     * turns "it did not work" into a selector fix.
     */
    fun describe(roots: List<AccessibilityNodeInfo>, limit: Int = 30): List<String> {
        val out = mutableListOf<String>()
        for ((index, root) in roots.withIndex()) {
            if (out.size >= limit) break
            out.add("-- window ${index + 1} of ${roots.size} --")
            walk(root) { node ->
                val label = label(node)
                if (label != null && label.length <= 40) {
                    out.add(if (node.isClickable) "[tap] $label" else label)
                }
                out.size < limit
            }
        }
        return out
    }

    private fun find(
        roots: List<AccessibilityNodeInfo>,
        role: Role,
        matchUnclickable: Boolean = false,
    ): Found? {
        for (root in roots) {
            var hit: Found? = null
            walk(root) { node ->
                val label = label(node)
                if (label != null && roleOf(label) == role) {
                    val target = clickableSelfOrAncestor(node)
                    if (target != null) {
                        hit = Found(target, label.take(40))
                        return@walk false
                    }
                    // A heading is not a button, but it still answers
                    // "is a sheet on screen".
                    if (matchUnclickable) {
                        hit = Found(node, label.take(40))
                        return@walk false
                    }
                }
                true
            }
            if (hit != null) return hit
        }
        return null
    }

    private fun label(node: AccessibilityNodeInfo): String? {
        val description = node.contentDescription?.toString()?.trim()
        if (!description.isNullOrEmpty()) return description
        return node.text?.toString()?.trim()?.takeIf { it.isNotEmpty() }
    }

    /**
     * The node itself if it takes taps, else the nearest parent that
     * does. A label is usually a child of the control it names.
     */
    private fun clickableSelfOrAncestor(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        var current: AccessibilityNodeInfo? = node
        var depth = 0
        while (current != null && depth < 5) {
            if (current.isClickable) return current
            current = current.parent
            depth++
        }
        return null
    }

    /** Breadth-first, capped. `visit` returns false to stop the walk. */
    private fun walk(root: AccessibilityNodeInfo?, visit: (AccessibilityNodeInfo) -> Boolean) {
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

    private const val MAX_NODES = 900
    private const val MAX_DEPTH = 40
}

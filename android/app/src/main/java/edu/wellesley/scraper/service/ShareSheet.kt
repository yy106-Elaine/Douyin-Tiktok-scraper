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
 */
object ShareSheet {

    /** How the share control identifies itself, in both apps. */
    private val SHARE = listOf(
        Regex("""share video""", RegexOption.IGNORE_CASE),
        Regex("""^share$""", RegexOption.IGNORE_CASE),
        Regex("""分享"""),
    )

    /** The "copy link" entry inside the sheet that opens. */
    private val COPY_LINK = listOf(
        Regex("""copy link""", RegexOption.IGNORE_CASE),
        Regex("""复制[链連鏈]接"""),
        Regex("""複製[鏈链連]接"""),
        Regex("""复制口令"""),
        Regex("""^copy$""", RegexOption.IGNORE_CASE),
    )

    /** A node, and the label that matched, for the run's log. */
    data class Found(val node: AccessibilityNodeInfo, val label: String)

    fun findShare(root: AccessibilityNodeInfo?): Found? = find(root, SHARE)

    fun findCopyLink(root: AccessibilityNodeInfo?): Found? = find(root, COPY_LINK)

    /**
     * What is on screen, for when a search failed.
     *
     * A run that cannot find its control is the expected failure --
     * the wording differs by app version and by language -- so the
     * useful thing is a list of what was there instead. This is what
     * turns "it did not work" into a selector fix.
     */
    fun describe(root: AccessibilityNodeInfo?, limit: Int = 30): List<String> {
        val out = mutableListOf<String>()
        walk(root) { node ->
            val label = label(node)
            if (label != null && label.length <= 40) {
                out.add(if (node.isClickable) "[tap] $label" else label)
            }
            out.size < limit
        }
        return out
    }

    private fun find(root: AccessibilityNodeInfo?, patterns: List<Regex>): Found? {
        var hit: Found? = null
        walk(root) { node ->
            val label = label(node)
            if (label != null && patterns.any { it.containsMatchIn(label) }) {
                val target = clickableSelfOrAncestor(node)
                if (target != null) {
                    hit = Found(target, label.take(40))
                    return@walk false
                }
            }
            true
        }
        return hit
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

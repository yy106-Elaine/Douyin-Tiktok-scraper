package edu.wellesley.scraper.parser

import android.view.accessibility.AccessibilityNodeInfo

/** Flattened view of one node, so the tree is walked exactly once. */
data class FlatNode(
    val viewId: String?,
    val text: String?,
    val description: String?,
    val className: String?,
    val top: Int,
)

object NodeTools {

    /** Depth-capped traversal; these feeds nest deeply and we are on a 500ms budget. */
    private const val MAX_DEPTH = 40
    private const val MAX_NODES = 600

    fun flatten(root: AccessibilityNodeInfo?): List<FlatNode> {
        if (root == null) return emptyList()
        val out = ArrayList<FlatNode>(64)
        val bounds = android.graphics.Rect()

        fun walk(node: AccessibilityNodeInfo?, depth: Int) {
            if (node == null || depth > MAX_DEPTH || out.size >= MAX_NODES) return
            node.getBoundsInScreen(bounds)
            out.add(
                FlatNode(
                    viewId = node.viewIdResourceName,
                    text = node.text?.toString()?.trim()?.ifEmpty { null },
                    description = node.contentDescription?.toString()?.trim()?.ifEmpty { null },
                    className = node.className?.toString(),
                    top = bounds.top,
                )
            )
            for (i in 0 until node.childCount) {
                walk(node.getChild(i), depth + 1)
            }
        }

        walk(root, 0)
        return out
    }

    /** First node whose view id ends with any of [suffixes]. */
    fun byViewId(nodes: List<FlatNode>, vararg suffixes: String): FlatNode? =
        nodes.firstOrNull { node ->
            val id = node.viewId ?: return@firstOrNull false
            suffixes.any { id.endsWith("/$it") }
        }

    /** First capture group of the first text/description matching [pattern]. */
    fun firstGroup(nodes: List<FlatNode>, pattern: Regex): String? {
        for (node in nodes) {
            for (candidate in listOfNotNull(node.description, node.text)) {
                pattern.find(candidate)?.groupValues?.getOrNull(1)?.let { return it.trim() }
            }
        }
        return null
    }

    fun anyMatches(nodes: List<FlatNode>, pattern: Regex): Boolean =
        nodes.any { node ->
            listOfNotNull(node.description, node.text).any { pattern.containsMatchIn(it) }
        }
}

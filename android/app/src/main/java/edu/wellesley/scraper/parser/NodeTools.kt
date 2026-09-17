package edu.wellesley.scraper.parser

import android.view.accessibility.AccessibilityNodeInfo

/** Flattened view of one node, so the tree is walked exactly once. */
data class FlatNode(
    val viewId: String?,
    val text: String?,
    val description: String?,
    val className: String?,
    val selected: Boolean,
    val depth: Int,
    val top: Int,
    /**
     * The node's extras bundle, flattened to text.
     *
     * Apps may attach their own data here, and a video id would be the
     * kind of thing that turns up in it. Read passively like everything
     * else, so it costs nothing to look.
     */
    val extras: String? = null,
)

object NodeTools {

    /** Depth-capped traversal; these feeds nest deeply and we are on a 500ms budget. */
    private const val MAX_DEPTH = 40
    private const val MAX_NODES = 900
    private const val MAX_EXTRA_KEYS = 12
    private const val MAX_EXTRA_VALUE_LENGTH = 80

    /**
     * Pre-order walk, so a node's descendants immediately follow it and
     * carry a greater depth. [descendantsOf] relies on that ordering.
     */
    fun flatten(root: AccessibilityNodeInfo?): List<FlatNode> {
        if (root == null) return emptyList()
        val out = ArrayList<FlatNode>(128)
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
                    selected = node.isSelected,
                    depth = depth,
                    top = bounds.top,
                    extras = flattenExtras(node),
                )
            )
            for (i in 0 until node.childCount) {
                walk(node.getChild(i), depth + 1)
            }
        }

        walk(root, 0)
        return out
    }

    /** Extras as "key=value" pairs, capped so a large bundle cannot stall a frame. */
    private fun flattenExtras(node: AccessibilityNodeInfo): String? {
        val extras = try {
            node.extras
        } catch (error: RuntimeException) {
            null
        } ?: return null

        val keys = extras.keySet()
        if (keys.isEmpty()) return null

        return keys.take(MAX_EXTRA_KEYS).joinToString(" ") { key ->
            val value = try {
                extras.get(key)?.toString()
            } catch (error: RuntimeException) {
                null
            }
            "$key=${value?.take(MAX_EXTRA_VALUE_LENGTH) ?: ""}"
        }
    }

    /**
     * Split a screen into one group per post.
     *
     * Both feeds keep more than one post in the tree at a time -- the next
     * video is preloaded off-screen -- so parsing the whole tree as a single
     * post bleeds fields from one video into another. Each app marks a post
     * root with a recognisable view id; everything from one such marker to
     * the next belongs to one post.
     *
     * Nodes before the first marker (status bar, feed tabs) are dropped.
     * When no marker is found at all the whole screen is returned as one
     * group, which is the right fallback for a single-post screen.
     */
    fun segment(nodes: List<FlatNode>, isBoundary: (FlatNode) -> Boolean): List<List<FlatNode>> {
        val starts = nodes.indices.filter { isBoundary(nodes[it]) }
        if (starts.isEmpty()) return if (nodes.isEmpty()) emptyList() else listOf(nodes)

        return starts.mapIndexed { index, start ->
            val end = starts.getOrNull(index + 1) ?: nodes.size
            nodes.subList(start, end)
        }.filter { it.isNotEmpty() }
    }

    /** Nodes nested under [index], using the pre-order depth ordering. */
    fun descendantsOf(nodes: List<FlatNode>, index: Int): List<FlatNode> {
        val depth = nodes[index].depth
        val out = ArrayList<FlatNode>()
        for (i in index + 1 until nodes.size) {
            if (nodes[i].depth <= depth) break
            out.add(nodes[i])
        }
        return out
    }

    /** First node whose view id ends with, or contains, any of [fragments]. */
    fun byViewId(nodes: List<FlatNode>, vararg fragments: String): FlatNode? =
        nodes.firstOrNull { node ->
            val id = node.viewId ?: return@firstOrNull false
            fragments.any { id.endsWith("/$it") || id.contains(it) }
        }

    /** First capture group of the first description/text matching [pattern]. */
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

    /**
     * A count shown next to an unlabelled icon: find the marker node by
     * [marker], then take the first number nested under it.
     */
    fun countUnderMarker(nodes: List<FlatNode>, marker: Regex, isCount: Regex): String? {
        val index = nodes.indexOfFirst { node ->
            listOfNotNull(node.description, node.text).any { marker.containsMatchIn(it) }
        }
        if (index < 0) return null
        return descendantsOf(nodes, index)
            .firstOrNull { it.text != null && isCount.matches(it.text) }
            ?.text
    }
}

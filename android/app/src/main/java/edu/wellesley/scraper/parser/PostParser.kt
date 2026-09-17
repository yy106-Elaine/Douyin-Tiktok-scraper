package edu.wellesley.scraper.parser

/**
 * Reads posts out of a flattened accessibility tree.
 *
 * Implementations are inherently version-specific: they are written
 * against the view ids and UI strings of one build of one app, and a
 * redesign breaks them silently. Keep the selector constants at the
 * top of each implementation so re-verifying against a fresh
 * `uiautomator dump` is a small edit. See docs/SELECTORS.md.
 */
interface PostParser {
    val platform: String

    /** Marks the root node of one post, used to split a screen into posts. */
    fun isPostBoundary(node: FlatNode): Boolean

    /** Which feed tab is selected. Read from the whole screen, not one post. */
    fun feed(nodes: List<FlatNode>): String?

    /** Parse one post's nodes, as produced by [NodeTools.segment]. */
    fun parse(nodes: List<FlatNode>): ParsedPost?

    /**
     * Why this frame must not be read, or null to read it.
     *
     * The comment sheet is the case that matters: a long comment is
     * easily mistaken for a caption, so the frame is dropped rather
     * than recorded wrongly. The reason is returned rather than a
     * boolean because an over-broad guard silently discards most of a
     * session, and the only way to notice is to see which rule fired.
     */
    fun skipReason(nodes: List<FlatNode>): String?
}

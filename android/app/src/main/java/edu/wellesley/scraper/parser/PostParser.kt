package edu.wellesley.scraper.parser

/**
 * Reads one post out of a flattened accessibility tree.
 *
 * Implementations are inherently version-specific: they are written
 * against the view ids and UI strings of one build of one app, and a
 * redesign breaks them silently. Keep the selector constants at the
 * top of each implementation so re-verifying against a fresh
 * `uiautomator dump` is a small edit. See docs/SELECTORS.md.
 */
interface PostParser {
    val platform: String

    fun parse(nodes: List<FlatNode>): ParsedPost?

    /**
     * True when the reading context is unsafe -- e.g. the comment
     * sheet is open, where a long comment is easily mistaken for the
     * caption. The service skips the frame entirely rather than
     * recording a wrong value.
     */
    fun shouldSkip(nodes: List<FlatNode>): Boolean
}

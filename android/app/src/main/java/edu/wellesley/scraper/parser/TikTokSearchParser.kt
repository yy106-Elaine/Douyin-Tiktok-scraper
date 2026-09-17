package edu.wellesley.scraper.parser

/**
 * TikTok's search results grid.
 *
 * This is the surface a keyword study actually samples from: a query
 * plus a recency filter, then everything returned. It is a better place
 * to read than the feed in two ways. A grid exposes several videos per
 * screen instead of one, and sampling a search result set says nothing
 * about what the recommender would have served -- so reading it cannot
 * be accused of measuring a feed the researcher's own behaviour shaped.
 *
 * Each result tile carries one content description of the form
 *
 *     Video by <author>, <caption> , Liked by <count> users
 *
 * which is the whole tile in a single string.
 */
class TikTokSearchParser : PostParser {

    override val platform: String = "tiktok"

    private companion object {
        /**
         * One result tile. The caption is allowed to be empty, and to
         * contain commas -- hence the greedy middle bounded by the
         * fixed " , Liked by " tail rather than a comma split.
         */
        val RESULT = Regex(
            """^Video by (.+?),\s*(.*?)\s*,\s*Liked by ([\d.,]+\s*[KMB]?) users?$""",
            RegexOption.IGNORE_CASE,
        )

        /** Present only on a search screen. */
        val SEARCH_MARKERS = listOf(
            Regex("""Clear search field""", RegexOption.IGNORE_CASE),
            Regex("""^Recently uploaded$""", RegexOption.IGNORE_CASE),
        )

        /** The query box; its text is the sampling frame. */
        val QUERY_VIEW_IDS = arrayOf("hgt", "search_input", "et_search_kw")

        val RESULT_TABS = setOf("Top", "Videos", "Users", "LIVE", "Shop", "Hashtags")
    }

    /** True when this looks like a search screen rather than a feed. */
    fun recognises(nodes: List<FlatNode>): Boolean =
        SEARCH_MARKERS.any { NodeTools.anyMatches(nodes, it) } && tiles(nodes).isNotEmpty()

    /**
     * Every result tile on screen.
     *
     * Unlike the feed, one frame holds many posts, so the caller reads
     * them all rather than segmenting and parsing one.
     */
    fun parseAll(nodes: List<FlatNode>): List<ParsedPost> {
        val query = query(nodes)
        val sort = sort(nodes)
        return tiles(nodes).mapNotNull { match ->
            val author = match.groupValues[1].trim().ifEmpty { null }
            val caption = match.groupValues[2].trim().ifEmpty { null }
            ParsedPost(
                platform = platform,
                authorName = author,
                caption = caption,
                likeRaw = match.groupValues[3].replace(" ", "").ifEmpty { null },
                // Recorded so every row carries the query that produced
                // it: a sample is not interpretable without its frame.
                feed = listOfNotNull("search", query, sort).joinToString(":"),
            ).takeIf { it.isUsable() }
        }
    }

    private fun tiles(nodes: List<FlatNode>): List<MatchResult> =
        nodes.mapNotNull { node ->
            node.description?.trim()?.let(RESULT::matchEntire)
        }

    private fun query(nodes: List<FlatNode>): String? =
        NodeTools.byViewId(nodes, *QUERY_VIEW_IDS)?.text?.trim()?.ifEmpty { null }

    /** Which sort the results are under, when one is selected. */
    private fun sort(nodes: List<FlatNode>): String? =
        nodes.firstOrNull { it.selected && it.text !in RESULT_TABS }?.text?.trim()
            ?.ifEmpty { null }

    // A search screen is not read post-by-post, so the single-post
    // members of the interface are not the route in. The service calls
    // parseAll instead; these keep the type honest.

    override fun isPostBoundary(node: FlatNode): Boolean = false

    override fun feed(nodes: List<FlatNode>): String? = query(nodes)?.let { "search:$it" }

    override fun parse(nodes: List<FlatNode>): ParsedPost? = parseAll(nodes).firstOrNull()

    override fun skipReason(nodes: List<FlatNode>): String? = null
}

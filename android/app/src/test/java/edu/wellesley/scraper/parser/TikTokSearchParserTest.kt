package edu.wellesley.scraper.parser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The search grid, from a device's own dump.
 *
 * A keyword study samples here, not from the feed: a query plus a
 * recency filter, then everything returned. The tile descriptions are
 * transcribed from what the app actually rendered.
 */
class TikTokSearchParserTest {

    private val parser = TikTokSearchParser()

    private fun node(
        viewId: String? = null,
        text: String? = null,
        description: String? = null,
        selected: Boolean = false,
    ) = FlatNode(viewId, text, description, null, selected, 1, 0)

    /** The search screen's chrome, as captured. */
    private val chrome = listOf(
        node(viewId = "hgt", text = "#wlw"),
        node(viewId = "lyi", description = "Search"),
        node(viewId = "cqu", description = "Clear search field"),
        node(text = "Top", description = "Top", selected = true),
        node(text = "Videos", description = "Videos"),
        node(text = "Users", description = "Users"),
        node(text = "All"),
        node(text = "Recently uploaded", selected = true),
        node(viewId = "tqe", text = "Ad"),
    )

    private fun tile(description: String) = node(viewId = "uk4", description = description)

    @Test
    fun `reads a result tile captured from the device`() {
        val nodes = chrome + tile("Video by 🐞, #wlw #viral , Liked by 330.3K users")
        val post = parser.parseAll(nodes).single()

        assertEquals("🐞", post.authorName)
        assertEquals("#wlw #viral", post.caption)
        assertEquals("330.3K", post.likeRaw)
    }

    @Test
    fun `harvests every tile on one screen`() {
        // The point of reading the grid: many posts per frame, where the
        // feed yields one.
        val nodes = chrome + listOf(
            tile("Video by alice, first clip , Liked by 1,204 users"),
            tile("Video by bob, second clip , Liked by 88 users"),
            tile("Video by carol, third clip , Liked by 9M users"),
        )
        val posts = parser.parseAll(nodes)

        assertEquals(3, posts.size)
        assertEquals(listOf("alice", "bob", "carol"), posts.map { it.authorName })
        assertEquals(listOf("1,204", "88", "9M"), posts.map { it.likeRaw })
    }

    @Test
    fun `records the query and sort each row came from`() {
        // A sample is not interpretable without its sampling frame.
        val nodes = chrome + tile("Video by alice, a clip , Liked by 10 users")
        assertEquals("search:#wlw:Recently uploaded", parser.parseAll(nodes).single().feed)
    }

    @Test
    fun `a caption containing commas survives`() {
        val nodes = chrome + tile("Video by dana, one, two, three , Liked by 5 users")
        assertEquals("one, two, three", parser.parseAll(nodes).single().caption)
    }

    @Test
    fun `an empty caption is null rather than blank`() {
        val nodes = chrome + tile("Video by erin,  , Liked by 5 users")
        val post = parser.parseAll(nodes).single()
        assertEquals("erin", post.authorName)
        assertNull(post.caption)
    }

    @Test
    fun `a feed screen is not mistaken for a search screen`() {
        val feedNodes = listOf(
            node(viewId = "widget_container"),
            node(description = "someuser profile"),
            node(description = "Like video. 976K likes"),
        )
        assertFalse(parser.recognises(feedNodes))
    }

    @Test
    fun `search chrome without result tiles is not claimed`() {
        // An empty result set, or results still loading, must fall
        // through rather than report a screen it cannot read.
        assertFalse(parser.recognises(chrome))
    }

    @Test
    fun `a search screen with tiles is claimed`() {
        val nodes = chrome + tile("Video by alice, a clip , Liked by 10 users")
        assertTrue(parser.recognises(nodes))
    }

    @Test
    fun `non-video descriptions on the screen are ignored`() {
        val nodes = chrome + listOf(
            node(description = "Liked by 300 users"),
            node(description = "Video by alice"),
            tile("Video by alice, a clip , Liked by 10 users"),
        )
        assertEquals(1, parser.parseAll(nodes).size)
    }
}

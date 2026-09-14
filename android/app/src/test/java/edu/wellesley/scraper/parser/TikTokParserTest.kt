package edu.wellesley.scraper.parser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Node fixtures mirror what TikTok's accessibility tree exposes:
 * counts in contentDescription, caption as undescribed text.
 */
class TikTokParserTest {

    private val parser = TikTokParser()

    private fun node(
        viewId: String? = null,
        text: String? = null,
        description: String? = null,
        selected: Boolean = false,
        depth: Int = 1,
        top: Int = 0,
    ) = FlatNode(viewId, text, description, null, selected, depth, top)

    private fun onePost(
        author: String = "someuser",
        caption: String = "a caption long enough to be recognised as one",
    ) = listOf(
        node(viewId = "com.zhiliaoapp.musically:id/widget_container", depth = 1),
        node(description = "$author profile", depth = 2),
        node(text = caption, depth = 2),
        node(description = "Like video. 74.9K likes", depth = 2),
        node(description = "Read or add comments. 1,234 comments", depth = 2),
        node(description = "Share video. 88 shares", depth = 2),
        node(description = "Sound: original sound - someuser", depth = 2),
    )

    @Test
    fun `reads counts from content descriptions`() {
        val post = parser.parse(onePost())!!
        assertEquals("74.9K", post.likeRaw)
        assertEquals("1,234", post.commentRaw)
        assertEquals("88", post.shareRaw)
    }

    @Test
    fun `reads author caption and music`() {
        val post = parser.parse(onePost())!!
        assertEquals("someuser", post.authorHandle)
        assertEquals("a caption long enough to be recognised as one", post.caption)
        assertEquals("original sound - someuser", post.music)
    }

    @Test
    fun `favourites count is taken from a child of the favourites button`() {
        val nodes = onePost() + listOf(
            node(description = "Favorites", depth = 2),
            node(text = "12.3K", depth = 3),
        )
        assertEquals("12.3K", parser.parse(nodes)!!.saveRaw)
    }

    @Test
    fun `a count outside the favourites button is not mistaken for it`() {
        val nodes = onePost() + listOf(
            node(description = "Favorites", depth = 2),
            node(text = "9.9K", depth = 2),
        )
        assertNull(parser.parse(nodes)!!.saveRaw)
    }

    @Test
    fun `two posts on one screen are separated at the container boundary`() {
        val nodes = onePost("alice", "alice's caption, long enough to count") +
            onePost("bob", "bob's caption, also long enough to count")

        val segments = NodeTools.segment(nodes, parser::isPostBoundary)
        assertEquals(2, segments.size)

        val parsed = segments.mapNotNull(parser::parse)
        assertEquals(listOf("alice", "bob"), parsed.map { it.authorHandle })
    }

    @Test
    fun `chrome before the first post is dropped`() {
        val nodes = listOf(node(text = "For You", selected = true, depth = 1)) + onePost()
        val segments = NodeTools.segment(nodes, parser::isPostBoundary)
        assertEquals(1, segments.size)
        assertEquals("someuser", parser.parse(segments.single())!!.authorHandle)
    }

    @Test
    fun `a screen with no container marker is parsed as a single post`() {
        val nodes = onePost().drop(1)
        assertEquals(1, NodeTools.segment(nodes, parser::isPostBoundary).size)
    }

    @Test
    fun `the selected feed tab is reported as a slug`() {
        val nodes = listOf(
            node(text = "For You", selected = true),
            node(text = "Following", selected = false),
        )
        assertEquals("recommend", parser.feed(nodes))
    }

    @Test
    fun `an open comment sheet is skipped`() {
        assertFalse(parser.shouldSkip(onePost()))
        assertTrue(parser.shouldSkip(onePost() + node(text = "Add comment")))
    }

    @Test
    fun `paid partnership counts as an ad`() {
        assertTrue(parser.parse(onePost() + node(text = "Paid partnership"))!!.isAd!!)
        assertFalse(parser.parse(onePost())!!.isAd!!)
    }

    @Test
    fun `the longest undescribed text wins as the caption`() {
        val nodes = onePost() + node(text = "a substantially longer caption than the first one")
        assertEquals("a substantially longer caption than the first one", parser.parse(nodes)!!.caption)
    }
}

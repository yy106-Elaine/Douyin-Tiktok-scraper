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
        assertEquals("someuser", post.authorName)
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
        assertEquals(listOf("alice", "bob"), parsed.map { it.authorName })
    }

    @Test
    fun `chrome before the first post is dropped`() {
        val nodes = listOf(node(text = "For You", selected = true, depth = 1)) + onePost()
        val segments = NodeTools.segment(nodes, parser::isPostBoundary)
        assertEquals(1, segments.size)
        assertEquals("someuser", parser.parse(segments.single())!!.authorName)
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
        assertNull(parser.skipReason(onePost()))

        // Only markers a sheet actually produces.
        for (marker in listOf("View 12 replies", "Reply to @someone", "1,204 comments")) {
            val reason = parser.skipReason(onePost() + node(text = marker))
            assertTrue("$marker should skip", reason != null)
        }
    }

    @Test
    fun `the feed's own comment affordances do not skip the frame`() {
        // A live session lost 24 of 31 frames to a guard that matched
        // the feed's own comment button and inline comment entry.
        for (onFeed in listOf("Add comment", "Read or add comments. 1,234 comments")) {
            assertNull(onFeed, parser.skipReason(onePost() + node(text = onFeed)))
        }
    }

    @Test
    fun `a skip names which marker fired`() {
        val reason = parser.skipReason(onePost() + node(text = "View 3 replies"))
        assertTrue(reason!!, reason.contains("reply thread"))
    }

    @Test
    fun `one visible tab label is taken as the active feed`() {
        // Not every build reports isSelected on the tab.
        assertEquals("recommend", parser.feed(listOf(node(text = "For You"))))
    }

    @Test
    fun `several visible tabs with none selected stays unknown`() {
        val nodes = listOf(node(text = "For You"), node(text = "Following"))
        assertNull(parser.feed(nodes))
    }

    @Test
    fun `paid partnership counts as an ad`() {
        assertTrue(parser.parse(onePost() + node(text = "Paid partnership"))!!.isAd!!)
        assertFalse(parser.parse(onePost())!!.isAd!!)
    }

    @Test
    fun `the expand affordance is stripped from the caption`() {
        // Real captures came back as "#kaicenat more" and "like oh ok ...more".
        for ((raw, expected) in listOf(
            "a caption that is long enough to be picked up more" to
                "a caption that is long enough to be picked up",
            "a caption that is long enough to be picked up ...more" to
                "a caption that is long enough to be picked up",
            "a caption that is long enough to be picked up…more" to
                "a caption that is long enough to be picked up",
        )) {
            val nodes = onePost(caption = raw)
            assertEquals(expected, parser.parse(nodes)!!.caption)
        }
    }

    @Test
    fun `a caption not ending in the affordance is left alone`() {
        val raw = "a caption mentioning more than one thing here"
        assertEquals(raw, parser.parse(onePost(caption = raw))!!.caption)
    }

    @Test
    fun `favourites read from an inline count in the description`() {
        val nodes = onePost() + node(description = "12.3K Favorites", depth = 2)
        assertEquals("12.3K", parser.parse(nodes)!!.saveRaw)
    }

    @Test
    fun `favourites read from a loosely labelled button`() {
        val nodes = onePost() + listOf(
            node(description = "Add to Favorites", depth = 2),
            node(text = "4,201", depth = 3),
        )
        assertEquals("4,201", parser.parse(nodes)!!.saveRaw)
    }

    @Test
    fun `the longest undescribed text wins as the caption`() {
        val nodes = onePost() + node(text = "a substantially longer caption than the first one")
        assertEquals(
            "a substantially longer caption than the first one",
            parser.parse(nodes)!!.caption,
        )
    }

    @Test
    fun `the author handle is read from a node that is only a handle`() {
        val nodes = onePost() + node(text = "@someuser")
        val post = parser.parse(nodes)!!
        assertEquals("someuser", post.authorHandle)
        assertEquals("someuser", post.authorName)
    }

    @Test
    fun `a mention inside the caption is not taken for the author`() {
        // Captions routinely tag other accounts; attributing the post to
        // whoever it tagged would send an interview request to the wrong
        // person.
        val nodes = onePost(caption = "big thanks to @otheraccount for the idea here")
        assertNull(parser.parse(nodes)!!.authorHandle)
    }

    @Test
    fun `a handle in the profile label is recognised`() {
        val nodes = listOf(
            node(viewId = "com.zhiliaoapp.musically:id/widget_container"),
            node(description = "@someuser profile"),
            node(text = "a caption long enough to be recognised as one"),
        )
        val post = parser.parse(nodes)!!
        assertEquals("someuser", post.authorHandle)
        assertEquals("someuser", post.authorName)
    }

    @Test
    fun `a display name with emoji is kept but yields no handle`() {
        // Real capture: "lilly 🤚 profile". Display names are not
        // account identifiers.
        val nodes = listOf(
            node(viewId = "com.zhiliaoapp.musically:id/widget_container"),
            node(description = "lilly \uD83E\uDD1A profile"),
            node(text = "a caption long enough to be recognised as one"),
        )
        val post = parser.parse(nodes)!!
        assertNull(post.authorHandle)
        assertEquals("lilly \uD83E\uDD1A", post.authorName)
    }
}

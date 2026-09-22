package edu.wellesley.scraper.parser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A real frame, transcribed from a device's self-check dump.
 *
 * Fixtures I invent encode what I expect the interface to look like,
 * which is exactly the assumption that has been wrong repeatedly here.
 * This one is what the app actually rendered, including the in-app
 * browser that happened to be open over the video -- and it is that
 * accident which revealed the caption being taken from a shop page.
 */
class TikTokLiveFrameTest {

    private val parser = TikTokParser()

    private fun node(viewId: String?, text: String?, description: String?) =
        FlatNode(viewId, text, description, null, false, 1, 0)

    /** The video's own nodes, as captured. */
    private val videoNodes = listOf(
        node("long_press_layout", null, "Video"),
        node("user_avatar", null, "SierraLocklear profile"),
        node("ihy", null, "Follow SierraLocklear"),
        node("fx6", null, "Like video. 976K likes"),
        node("ehl", null, "Read or add comments. 7,143 comments"),
        node("hu_", null, "Add or remove this video from Favorites."),
        node("p2d", null, "Sound: Yes you can (RMX) by KayArchonn"),
        node("fx6", null, "Share video. 116.4K shares"),
        node("title", "SierraLocklear", null),
        node("tv_post_time", "· 2025-05-31", null),
    )

    /** The in-app browser that was open over it: a shop page. */
    private val browserNodes = listOf(
        node("e42", null, "Close"),
        node("p7v", "www.aelfriceden.com", "www.aelfriceden.com"),
        node("shopify-pc__banner__body-title", "We value your privacy", null),
        node(
            null,
            "We use cookies and other technologies to personalise your experience",
            null,
        ),
        node("shopify-pc__banner__btn-accept", "Accept", null),
        node(null, "Aelfric Eden Boxy Fireman Clasp Jacket · $79.00", null),
        node(null, "AELFRIC EDEN BOXY FIREMAN CLASP JACKET", null),
    )

    @Test
    fun `reads the counts the interface does expose`() {
        val post = parser.parse(videoNodes)!!
        assertEquals("976K", post.likeRaw)
        assertEquals("7,143", post.commentRaw)
        assertEquals("116.4K", post.shareRaw)
    }

    @Test
    fun `saves stays empty because this build publishes no count`() {
        // "Add or remove this video from Favorites." carries no number,
        // and no child of it does either. Unavailable, not unparsed.
        assertNull(parser.parse(videoNodes)!!.saveRaw)
    }

    @Test
    fun `reads the publication date`() {
        // The variable a takedown study measures from.
        assertEquals("2025-05-31", parser.parse(videoNodes)!!.postedAtRaw)
    }

    @Test
    fun `reads the display name and finds no handle`() {
        val post = parser.parse(videoNodes)!!
        assertEquals("SierraLocklear", post.authorName)
        assertNull(post.authorHandle)
    }

    @Test
    fun `reads the sound`() {
        assertEquals(
            "Yes you can (RMX) by KayArchonn",
            parser.parse(videoNodes)!!.music,
        )
    }

    @Test
    fun `a page open in the in-app browser is not stored as the caption`() {
        // What went wrong live: caption came back as
        // "We use cookies and other technologies to personali".
        val post = parser.parse(videoNodes + browserNodes)!!
        assertNull(post.caption)
    }

    @Test
    fun `the video's counts survive the browser being open`() {
        // The overlay hijacks the caption, not the engagement labels,
        // so the frame is still worth keeping.
        val post = parser.parse(videoNodes + browserNodes)!!
        assertEquals("976K", post.likeRaw)
        assertEquals("SierraLocklear", post.authorName)
        assertEquals("2025-05-31", post.postedAtRaw)
    }

    @Test
    fun `the display name is recovered from the follow button alone`() {
        val withoutProfileLabel = videoNodes.filter {
            it.description?.contains("profile") != true && it.viewId != "title"
        }
        assertEquals(
            "SierraLocklear",
            parser.parse(withoutProfileLabel)!!.authorName,
        )
    }

    @Test
    fun `the feed tab is absent from a fullscreen video frame`() {
        // Which is why the service carries the last observed tab
        // forward instead of storing null on most rows.
        assertNull(parser.feed(videoNodes))
    }

    @Test
    fun `this frame is not mistaken for an open comment sheet`() {
        assertNull(parser.skipReason(videoNodes))
        assertNull(parser.skipReason(videoNodes + browserNodes))
    }

    @Test
    fun `no video id is present anywhere in a real frame`() {
        // Measured, not assumed: 0 of 58 frames on the device.
        assertNull(IdScanner.bestId(videoNodes + browserNodes))
    }

    // ---- A second live frame: two videos plus the comment bar ----

    /**
     * Transcribed from a dump where one screen held two videos and the
     * comment composer. Both are what went wrong: the two posts were
     * merged into one row, and the composer's "mention" control became
     * the author's handle.
     */
    private val twoVideoFrame = listOf(
        node("long_press_layout", null, "Video"),
        node("user_avatar", null, "Sophia Belle profile"),
        node("ihy", null, "Follow Sophia Belle"),
        node("fx6", null, "Like video. 92 likes"),
        node("ehl", null, "Read or add comments. 3 comments"),
        node("hu_", null, "Add or remove this video from Favorites."),
        node("p2d", null, "Original sound by Sophia Belle"),
        node("fx6", null, "Share video. 8 shares"),
        node("title", "Sophia Belle", null),
        node("tv_post_time", "· 11h ago", null),
        node("desc", "We also got a hotel room this night we knew each other prior", null),
        node("uia", "Search · wlw relationship moments", null),

        node("long_press_layout", null, "Video"),
        node("user_avatar", null, "MamaCann profile"),
        node("ihy", null, "Follow MamaCann"),
        node("fx6", null, "Like video. 56.4K likes"),
        node("ehl", null, "Read or add comments. 185 comments"),
        node("p2d", null, "Original sound by Pablo Prince"),
        node("fx6", null, "Share video. 3,155 shares"),
        node("title", "MamaCann", null),
        node("tv_post_time", "· 19h ago", null),
        node("desc", "great library of alexandria type beat #wlw #activism", null),

        node("ed5", "Add comment...", null),
        node("kgq", null, "@2131823198"),
        node("lcn", null, "Mention someone"),
    )

    @Test
    fun `two videos on one screen become two posts`() {
        // They were merged: this build has no widget_container, so the
        // whole tree was read as a single post.
        val segments = NodeTools.segment(twoVideoFrame, parser::isPostBoundary)
        val posts = segments.mapNotNull(parser::parse)

        assertEquals(listOf("Sophia Belle", "MamaCann"), posts.map { it.authorName })
        assertEquals(listOf("92", "56.4K"), posts.map { it.likeRaw })
        assertEquals(listOf("11h ago", "19h ago"), posts.map { it.postedAtRaw })
    }

    @Test
    fun `the comment bar's mention control is not the author's handle`() {
        // It renders as "@<numeric user id>", and was stored as the
        // handle for every row in a live session.
        val posts = NodeTools.segment(twoVideoFrame, parser::isPostBoundary)
            .mapNotNull(parser::parse)
        assertTrue(posts.isNotEmpty())
        posts.forEach { assertNull(it.authorHandle) }
    }

    @Test
    fun `a real handle is still accepted`() {
        // Inside the first post's own segment, where a handle would
        // actually be rendered -- appending it to the screen would put
        // it in the next post's segment instead.
        val nodes = twoVideoFrame.flatMap { node ->
            if (node.viewId == "title" && node.text == "Sophia Belle") {
                listOf(node, node(null, "@sophiabelle", null))
            } else {
                listOf(node)
            }
        }

        val posts = NodeTools.segment(nodes, parser::isPostBoundary)
            .mapNotNull(parser::parse)
        assertEquals("sophiabelle", posts[0].authorHandle)
        // The second post has none of its own, and must not borrow it.
        assertNull(posts[1].authorHandle)
    }

    @Test
    fun `the strip on screen is TikTok's suggestion, not the query`() {
        // This frame is a real capture, and "wlw relationship
        // moments" was taken for the search that produced it until a
        // run proved otherwise: `Chinese lesbian` was the only term
        // typed and the rows came back under 14 different phrases,
        // none of them that one. TikTok writes the phrase per video
        // from the video's own content, so it is kept, prefixed, and
        // never read as the sampling frame.
        assertEquals(
            "anchor:wlw relationship moments",
            parser.feed(twoVideoFrame),
        )
    }

    @Test
    fun `each post keeps its own caption`() {
        val posts = NodeTools.segment(twoVideoFrame, parser::isPostBoundary)
            .mapNotNull(parser::parse)
        assertEquals(
            "We also got a hotel room this night we knew each other prior",
            posts[0].caption,
        )
        assertEquals(
            "great library of alexandria type beat #wlw #activism",
            posts[1].caption,
        )
    }
}

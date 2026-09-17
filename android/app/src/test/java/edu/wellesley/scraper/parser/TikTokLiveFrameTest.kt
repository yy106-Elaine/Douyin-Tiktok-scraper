package edu.wellesley.scraper.parser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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
}

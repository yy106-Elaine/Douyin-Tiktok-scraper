package edu.wellesley.scraper.parser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Whether either app renders a video id anywhere is the question that
 * decides how a citable link can be obtained at all, so the scan needs
 * to be both sensitive and not fooled by the other numbers on screen.
 */
class IdScannerTest {

    private fun node(
        viewId: String? = null,
        text: String? = null,
        description: String? = null,
    ) = FlatNode(viewId, text, description, null, false, 1, 0)

    @Test
    fun `finds an id in a content description`() {
        val nodes = listOf(node(description = "video 7301234567890123456"))
        assertEquals("7301234567890123456", IdScanner.bestId(nodes))
    }

    @Test
    fun `finds an id in a view id`() {
        val nodes = listOf(node(viewId = "com.zhiliaoapp.musically:id/7301234567890123456"))
        assertEquals("7301234567890123456", IdScanner.bestId(nodes))
    }

    @Test
    fun `finds an id in plain text`() {
        assertEquals(
            "7301234567890123456",
            IdScanner.bestId(listOf(node(text = "7301234567890123456"))),
        )
    }

    @Test
    fun `engagement counts are not mistaken for ids`() {
        val nodes = listOf(
            node(description = "Like video. 74.9K likes"),
            node(description = "Read or add comments. 1,234 comments"),
            node(text = "123456"),
            node(text = "2026-09-14"),
        )
        assertNull(IdScanner.bestId(nodes))
    }

    @Test
    fun `a longer digit run is not truncated into an id`() {
        // A 22-digit tracking number must not yield its first 19 digits.
        val nodes = listOf(node(text = "7301234567890123456789"))
        assertNull(IdScanner.bestId(nodes))
    }

    @Test
    fun `an id in the current era outranks a bare digit run`() {
        val nodes = listOf(
            node(text = "123456789012345678"),
            node(text = "7301234567890123456"),
        )
        assertEquals("7301234567890123456", IdScanner.bestId(nodes))
    }

    @Test
    fun `an eighteen digit run still counts as a weak candidate`() {
        val hits = IdScanner.scan(listOf(node(text = "685123456789012345")))
        assertEquals(1, hits.size)
        assertEquals(false, hits.single().strong)
    }

    @Test
    fun `describe says plainly when nothing id-shaped is present`() {
        assertEquals(
            "no id-shaped token on screen",
            IdScanner.describe(listOf(node(text = "Like video. 74.9K likes"))),
        )
    }

    @Test
    fun `describe names where the id was found`() {
        val summary = IdScanner.describe(listOf(node(description = "7301234567890123456")))
        assertTrue(summary, summary.contains("7301234567890123456"))
        assertTrue(summary, summary.contains("desc"))
    }

    @Test
    fun `the parser attaches an id it finds on screen`() {
        val parser = TikTokParser()
        val nodes = listOf(
            node(viewId = "com.zhiliaoapp.musically:id/widget_container"),
            node(description = "someuser profile"),
            node(text = "a caption long enough to be recognised as one"),
            node(description = "aweme 7301234567890123456"),
        )
        assertEquals("7301234567890123456", parser.parse(nodes)!!.videoIdHint)
    }

    @Test
    fun `the parser reports no id when the screen has none`() {
        val parser = TikTokParser()
        val nodes = listOf(
            node(viewId = "com.zhiliaoapp.musically:id/widget_container"),
            node(description = "someuser profile"),
            node(text = "a caption long enough to be recognised as one"),
        )
        assertNull(parser.parse(nodes)!!.videoIdHint)
    }
}

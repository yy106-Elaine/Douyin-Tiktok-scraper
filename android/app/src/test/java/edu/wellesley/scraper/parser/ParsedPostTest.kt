package edu.wellesley.scraper.parser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ParsedPostTest {

    @Test
    fun `fingerprint combines platform author and caption prefix`() {
        val post = ParsedPost(
            platform = "douyin",
            authorName = "someone",
            caption = "0123456789012345678901234567890",
        )
        assertEquals("douyin::someone::01234567890123456789", post.fingerprint())
    }

    @Test
    fun `a post with neither author nor caption has no identity`() {
        val post = ParsedPost(platform = "douyin", likeRaw = "10万")
        assertNull(post.fingerprint())
        assertFalse(post.isUsable())
    }

    @Test
    fun `a display name alone is enough to identify a post`() {
        assertTrue(ParsedPost(platform = "douyin", authorName = "someone").isUsable())
    }

    @Test
    fun `payload keeps counts as displayed strings`() {
        val payload = ParsedPost(platform = "douyin", likeRaw = "12.3万").toPayload()
        assertEquals("12.3万", payload["like_raw"])
    }

    @Test
    fun `a post seen during a run stays marked as collected by it`() {
        // A run's own sighting is what makes the row part of the
        // corpus; a later sighting off the feed must not unmark it.
        val duringRun = ParsedPost(platform = "tiktok", duringRun = true)
        val byHand = ParsedPost(platform = "tiktok", caption = "later", duringRun = false)

        assertEquals(true, duringRun.mergedWith(byHand).duringRun)
        assertEquals(true, byHand.mergedWith(duringRun).duringRun)
    }

    @Test
    fun `the mark reaches the payload`() {
        val post = ParsedPost(platform = "tiktok", duringRun = false)
        assertEquals(false, post.toPayload()["during_run"])
    }
}

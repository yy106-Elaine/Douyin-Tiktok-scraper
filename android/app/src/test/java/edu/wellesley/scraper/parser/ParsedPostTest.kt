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
            authorHandle = "someone",
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
    fun `an author alone is enough to identify a post`() {
        assertTrue(ParsedPost(platform = "douyin", authorHandle = "someone").isUsable())
    }

    @Test
    fun `payload keeps counts as displayed strings`() {
        val payload = ParsedPost(platform = "douyin", likeRaw = "12.3万").toPayload()
        assertEquals("12.3万", payload["like_raw"])
    }
}

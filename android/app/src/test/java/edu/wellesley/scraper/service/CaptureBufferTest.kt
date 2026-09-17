package edu.wellesley.scraper.service

import edu.wellesley.scraper.parser.ParsedPost
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureBufferTest {

    private var clock = 0L
    private fun buffer() = CaptureBuffer(settleMillis = 5_000L, now = { clock })

    private fun post(like: String? = null, caption: String? = "hello world") = ParsedPost(
        platform = "tiktok",
        authorName = "someuser",
        caption = caption,
        likeRaw = like,
    )

    @Test
    fun `a post is not emitted while it is still on screen`() {
        val buffer = buffer()
        buffer.observe(post())
        clock += 1_000
        assertTrue(buffer.drain().isEmpty())
    }

    @Test
    fun `a post settles once it has not been seen for the settle window`() {
        val buffer = buffer()
        buffer.observe(post())
        clock += 6_000
        assertEquals(1, buffer.drain().size)
    }

    @Test
    fun `partial reads of the same post are merged`() {
        val buffer = buffer()
        buffer.observe(post(like = null))
        clock += 500
        buffer.observe(post(like = "12.3万"))
        clock += 6_000

        val (merged, _) = buffer.drain().single()
        assertEquals("12.3万", merged.likeRaw)
        assertEquals("hello world", merged.caption)
    }

    @Test
    fun `a field going out of view does not erase what was already read`() {
        val buffer = buffer()
        buffer.observe(post(like = "999"))
        clock += 500
        buffer.observe(post(like = null))
        clock += 6_000

        assertEquals("999", buffer.drain().single().first.likeRaw)
    }

    @Test
    fun `the reported timestamp is when the post was first seen`() {
        val buffer = buffer()
        clock = 1_000
        buffer.observe(post())
        clock = 3_000
        buffer.observe(post())
        clock = 9_000

        assertEquals(1_000L, buffer.drain().single().second)
    }

    @Test
    fun `force drains posts that have not settled`() {
        val buffer = buffer()
        buffer.observe(post())
        assertEquals(1, buffer.drain(force = true).size)
        assertEquals(0, buffer.size())
    }

    @Test
    fun `posts without any identity are ignored`() {
        val buffer = buffer()
        buffer.observe(ParsedPost(platform = "tiktok"))
        assertEquals(0, buffer.size())
    }
}

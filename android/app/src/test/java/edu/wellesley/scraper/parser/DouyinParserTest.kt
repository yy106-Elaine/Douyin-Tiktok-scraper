package edu.wellesley.scraper.parser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Built from a screen dump taken on the study phone, so these are the
 * strings Douyin actually renders rather than strings invented to match
 * the selectors.
 */
class DouyinParserTest {

    private fun node(id: String?, text: String?, description: String?) = FlatNode(
        viewId = id?.let { "com.ss.android.ugc.aweme:id/$it" },
        text = text,
        description = description,
        className = null,
        selected = false,
        depth = 2,
        top = 0,
    )

    /** One post, exactly as the accessibility tree presented it. */
    private val post = listOf(
        node("j+w", null, "关注"),
        node("user_avatar", null, "我爱吃葡萄"),
        node("gzs", null, "未点赞，喜欢17，按钮"),
        node("e=0", null, "评论5，按钮"),
        node("d_r", null, "未选中，收藏收藏，按钮"),
        node("z4_", null, "分享，按钮"),
        node("s6k", null, "音乐，@我爱吃葡萄创作的原声，按钮"),
        node("title", "@我爱吃葡萄", null),
        node("41=", "· 17小时前", "发布时间：17小时前"),
        node("desc", "许愿这次别再丢下我#lwl#lwl", null),
    )

    @Test
    fun `publication time is read from the labelled description`() {
        assertEquals("17小时前", DouyinParser().parse(post)?.postedAtRaw)
    }

    @Test
    fun `it falls back to the text form when the label is absent`() {
        val unlabelled = post.map {
            if (it.text == "· 17小时前") node("41=", "· 17小时前", null) else it
        }
        assertEquals("17小时前", DouyinParser().parse(unlabelled)?.postedAtRaw)
    }

    @Test
    fun `a caption is not mistaken for a publication time`() {
        // The fallback matches a bare relative time behind a separator.
        // A caption that happens to start with one must not qualify.
        val misleading = post.map {
            if (it.text == "· 17小时前") node("desc", "· 想你的第三天", null) else it
        }
        assertNull(DouyinParser().parse(misleading)?.postedAtRaw)
    }

    @Test
    fun `the rest of the post still parses`() {
        val parsed = DouyinParser().parse(post)
        assertEquals("我爱吃葡萄", parsed?.authorName)
        assertEquals("许愿这次别再丢下我#lwl#lwl", parsed?.caption)
        assertEquals("17", parsed?.likeRaw)
        assertEquals("5", parsed?.commentRaw)
    }
}

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
    fun `the share sheet is not a post`() {
        // Read off the study phone with the sheet open. This frame put
        // a row in the corpus captioned 链接已复制成功，去粘贴分享：.
        val sheet = listOf(
            node("z3h", "分享给", null),
            node("doy", null, "取消"),
            node("zyt", "转发到日常", null),
            node("zyt", "分享链接", null),
            node("zyt", "推荐", null),
            node("zyt", "合拍", null),
            node("zyt", "帮上热门", null),
            node("zyt", "举报", null),
        )
        assertEquals("share sheet open", DouyinParser().skipReason(sheet))
    }

    @Test
    fun `the comment bar is not a caption`() {
        // Douyin writes a different placeholder for different posts,
        // and each one was being stored as a video of its own.
        for (placeholder in listOf(
            "爱评论的人，运气不会差",
            "期待你的评论",
            "有爱评论，说点儿好听的",
            "链接已复制成功，去粘贴分享：",
        )) {
            val frame = listOf(
                node("e3n", placeholder, null),
                node("6o_", null, "进度条"),
            )
            assertNull(
                "$placeholder was stored as a post",
                DouyinParser().parse(frame)?.caption,
            )
        }
    }

    @Test
    fun `a real caption that mentions comments still parses`() {
        val frame = post.map {
            if (it.text == "许愿这次别再丢下我#lwl#lwl") {
                node("desc", "评论区的姐妹都好可爱#lwl", null)
            } else {
                it
            }
        }
        assertEquals("评论区的姐妹都好可爱#lwl", DouyinParser().parse(frame)?.caption)
    }

    @Test
    fun `two videos in one frame do not become one`() {
        // The whole of "Last screen read" from the study phone, two
        // posts deep. Before the boundary was fixed this frame yielded
        // a single post: 沽月's avatar with 珩舟's caption, or the other
        // way round depending on node order -- and the corpus has rows
        // that were built that way.
        val frame = listOf(
            node("j+w", null, "关注"),
            node("user_avatar", null, "沽月"),
            node("gzs", null, "未点赞，喜欢24，按钮"),
            node("e=0", null, "评论8，按钮"),
            node("d_r", null, "未选中，收藏收藏，按钮"),
            node("z4_", null, "分享，按钮"),
            node("title", "@沽月", null),
            node("41=", "· 17小时前", "发布时间：17小时前"),
            node("desc", "今夜的风悄悄月悄悄 吻你的眉梢#lwl #最帅", null),
            node("j+w", null, "关注"),
            node("user_avatar", null, "珩舟"),
            node("gzs", null, "未点赞，喜欢7，按钮"),
            node("e=0", null, "评论1，按钮"),
            node("z4_", null, "分享，按钮"),
            node("title", "@珩舟", null),
            node("41=", "· 18小时前", "发布时间：18小时前"),
            node("desc", "出现#卡点#lwl", null),
        )

        val parser = DouyinParser()
        val posts = NodeTools.segment(frame, parser::isPostBoundary)
            .mapNotNull(parser::parse)

        assertEquals(2, posts.size)
        assertEquals("沽月", posts[0].authorName)
        assertEquals("今夜的风悄悄月悄悄 吻你的眉梢#lwl #最帅", posts[0].caption)
        assertEquals("24", posts[0].likeRaw)
        assertEquals("17小时前", posts[0].postedAtRaw)

        assertEquals("珩舟", posts[1].authorName)
        assertEquals("出现#卡点#lwl", posts[1].caption)
        assertEquals("7", posts[1].likeRaw)
        assertEquals("18小时前", posts[1].postedAtRaw)

        // The point of the whole fix: two videos, two identities.
        assertEquals(2, posts.mapNotNull { it.fingerprint() }.distinct().size)
    }

    @Test
    fun `interface text with no author behind it is not a post`() {
        // The first three were in the blocklist; the last two arrived
        // in the next run from a part of the interface nobody had
        // listed, which is why the test that matters is structural.
        for (chrome in listOf(
            "爱评论的人，运气不会差",
            "期待你的评论",
            "链接已复制成功，去粘贴分享：",
            "发条评论，说说你的感受",
            "未注册的手机号验证通过后将自动注册",
        )) {
            val frame = listOf(
                node("e3n", chrome, null),
                node("6o_", null, "进度条"),
            )
            assertNull("$chrome was stored as a post", DouyinParser().parse(frame))
        }
    }

    @Test
    fun `a post whose caption was not read is still a post`() {
        // Real, from the corpus: 愛樂 with 77 likes, caught before the
        // caption and the @name had rendered. Only the avatar names
        // the author in this frame, and the parser was not reading it
        // -- so the row had no author, which is what interface text
        // looks like. An author and counts are enough.
        val frame = listOf(
            node("user_avatar", null, "愛樂"),
            node("gzs", null, "未点赞，喜欢77，按钮"),
            node("e=0", null, "评论6，按钮"),
        )
        val parsed = DouyinParser().parse(frame)
        assertEquals("愛樂", parsed?.authorName)
        assertEquals("愛樂", parsed?.authorHandle)
        assertEquals("77", parsed?.likeRaw)
    }

    @Test
    fun `the at-name is the handle when no 抖音号 is on screen`() {
        // Douyin does not render its stable id in the feed, so the
        // column was always empty. The @name is the identifier the
        // platform actually uses.
        assertEquals("我爱吃葡萄", DouyinParser().parse(post)?.authorHandle)
    }

    @Test
    fun `a 抖音号 on screen wins over the at-name`() {
        val withId = post + node(null, "抖音号：grape_2024", null)
        assertEquals("grape_2024", DouyinParser().parse(withId)?.authorHandle)
    }

    @Test
    fun `a profile over the feed is not a post`() {
        // Both windows flatten into one frame while a profile is open,
        // and the 抖音号 on it then lands inside whichever feed segment
        // came last. A real run stored handle=zz272328 on a post by
        // Devil; the id belongs to zz7, whose profile was on screen.
        val frame = post + listOf(
            node("tp6", null, "zz7，复制名字"),
            node("57l", "抖音号：zz272328", null),
            node("2no", null, "返回顶部"),
        )
        assertEquals("profile page open", DouyinParser().skipReason(frame))
    }

    @Test
    fun `an ordinary post is not mistaken for a profile`() {
        assertNull(DouyinParser().skipReason(post))
    }

    @Test
    fun `the author line is not used as a caption`() {
        // Real: a frame caught before the caption rendered, where the
        // longest remaining text is the @name. A row went in reading
        // caption=@咸鱼不闲（求推荐版）, and a caption is stored verbatim
        // -- wrong is permanent, empty is a gap the next frame fills.
        val frame = listOf(
            node("user_avatar", null, "咸鱼不闲（求推荐版）"),
            node("gzs", null, "未点赞，喜欢106，按钮"),
            node("e=0", null, "评论9，按钮"),
            node("title", "@咸鱼不闲（求推荐版）", null),
            node("41=", "· 4小时前", "发布时间：4小时前"),
        )
        val parsed = DouyinParser().parse(frame)
        assertNull(parsed?.caption)
        // The rest of the row is still worth keeping.
        assertEquals("咸鱼不闲（求推荐版）", parsed?.authorName)
        assertEquals("106", parsed?.likeRaw)
        assertEquals("4小时前", parsed?.postedAtRaw)
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

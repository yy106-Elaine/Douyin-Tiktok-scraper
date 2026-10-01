package edu.wellesley.scraper.service

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The decisions a grid run makes, tested without a device.
 *
 * Everything here is a string question -- which cell is a post, which
 * one has been opened already -- and string questions are the ones
 * that have gone wrong before: two builds were spent guessing at
 * share-sheet wording. The node walking cannot be tested off a device,
 * so what matters is that it hands these functions the labels and that
 * these functions are right.
 */
class SearchGridTest {

    @Test
    fun `a tab is not a post`() {
        // Tapping a tab reloads the grid underneath it, which loses
        // the place and collects nothing.
        assertFalse(SearchGrid.isPostLabel("综合"))
        assertFalse(SearchGrid.isPostLabel("图文"))
        assertFalse(SearchGrid.isPostLabel("取消"))
        assertFalse(SearchGrid.isPostLabel("最多点赞"))
    }

    @Test
    fun `a badge is not a post`() {
        // A count is nothing once its digits are dropped, which is
        // what keeps it out: see fingerprint.
        assertFalse(SearchGrid.isPostLabel(SearchGrid.fingerprint("1.2万")))
        assertFalse(SearchGrid.isPostLabel("广告"))
    }

    @Test
    fun `an action on someone else's account is never a post`() {
        // Pinned, like the feed loop's own list. A cell opener that
        // chose what to tap by "it had text and it was clickable"
        // would otherwise press one of these the first time one
        // turned up inside the grid.
        assertFalse(SearchGrid.isPostLabel("关注"))
        assertFalse(SearchGrid.isPostLabel("建群分享"))
        assertFalse(SearchGrid.isPostLabel("合拍"))
        assertFalse(SearchGrid.isPostLabel("举报"))
        assertFalse(SearchGrid.isPostLabel("分享到日常"))
        assertFalse(SearchGrid.isPostLabel("下载"))
        // And the share sheet's own wording, which is a control too.
        assertFalse(SearchGrid.isPostLabel("分享链接"))
    }

    @Test
    fun `a title is a post`() {
        assertTrue(SearchGrid.isPostLabel("拉拉们都是怎么谈上的啊 #lwl #le"))
        assertTrue(SearchGrid.isPostLabel("和老婆的第三年"))
    }

    @Test
    fun `the same cell read twice is the same cell`() {
        // The like count ticks over and the description grows a line
        // once the thumbnail loads, so a raw compare would open the
        // post twice and never reach the next one.
        val first = SearchGrid.fingerprint("和老婆的第三年   #wlw\n1.2万赞")
        val again = SearchGrid.fingerprint("和老婆的第三年 #wlw 1.3万赞")
        assertEquals(first, again)
        // And the title itself survives: this is not reducing every
        // cell to the same string.
        assertTrue(first.startsWith("和老婆的第三年"))
    }

    @Test
    fun `the next cell is the first one not opened yet`() {
        val labels = listOf("第一条 post", "第二条 post", "第三条 post")

        assertEquals(0, SearchGrid.pick(labels, emptySet()))
        assertEquals(
            1,
            SearchGrid.pick(labels, setOf(SearchGrid.fingerprint("第一条 post"))),
        )
    }

    @Test
    fun `nothing new on screen is not the end of the run`() {
        // Null means scroll, and only a scroll that turns up nothing
        // new twice over ends the run -- see AutoCapture.BARREN_SCROLLS.
        val labels = listOf("第一条 post", "第二条 post")
        val done = labels.map(SearchGrid::fingerprint).toSet()

        assertNull(SearchGrid.pick(labels, done))
    }

    @Test
    fun `a cell that scrolled into a different position is still itself`() {
        // Coming back out of a post does not always restore the scroll
        // offset. An index would re-open a cell and skip another; the
        // label does not move with the grid.
        val before = listOf("甲 post", "乙 post", "丙 post")
        val after = listOf("乙 post", "丙 post", "丁 post")
        val done = setOf(SearchGrid.fingerprint("甲 post"), SearchGrid.fingerprint("乙 post"))

        assertEquals(0, SearchGrid.pick(before.drop(2), setOf()))
        assertEquals(1, SearchGrid.pick(after, done))
    }
}

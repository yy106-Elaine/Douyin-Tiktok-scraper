package edu.wellesley.scraper.service

import edu.wellesley.scraper.service.ShareSheet.Role
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The labels below were read off real share sheets in both apps, so
 * this is the one part of assisted capture that can be checked without
 * a phone.
 *
 * It earns its place: the copy entry was guessed at for two builds as
 * 复制链接, and Douyin actually writes 分享链接 -- a run would have
 * found nothing and stopped on the first video. The assertions that
 * matter most are the negative ones. 建群分享 contains 分享 and creates
 * a group chat; mistaking it for the share control would have this
 * pressing something that acts on other people's accounts.
 */
class ShareSheetTest {

    @Test
    fun `the share control is recognised in both apps`() {
        // Douyin's contentDescription, from a device dump.
        assertEquals(Role.SHARE, ShareSheet.roleOf("分享，按钮"))
        assertEquals(Role.SHARE, ShareSheet.roleOf("分享"))
        assertEquals(Role.SHARE, ShareSheet.roleOf("Share video"))
        assertEquals(Role.SHARE, ShareSheet.roleOf("share"))
    }

    @Test
    fun `the copy entry is recognised by the word each app actually uses`() {
        assertEquals(Role.COPY_LINK, ShareSheet.roleOf("分享链接"))
        assertEquals(Role.COPY_LINK, ShareSheet.roleOf("Copy link"))
        // Wordings not seen on this build but in circulation elsewhere.
        assertEquals(Role.COPY_LINK, ShareSheet.roleOf("复制链接"))
        assertEquals(Role.COPY_LINK, ShareSheet.roleOf("複製鏈接"))
    }

    @Test
    fun `an open sheet is recognised, including the second one Douyin stacks`() {
        assertEquals(Role.SHEET, ShareSheet.roleOf("分享给"))
        assertEquals(Role.SHEET, ShareSheet.roleOf("Send to"))
        assertEquals(Role.SHEET, ShareSheet.roleOf("链接已复制"))
        assertEquals(Role.SHEET, ShareSheet.roleOf("链接已复制成功，去粘贴分享："))
    }

    @Test
    fun `the comment box placeholder is not the share control`() {
        // 分享你此刻的想法 -- "share what you are thinking" -- is the
        // comment box. A prefix match took it for the share button, a
        // run tapped it, and the session ended up on the search
        // results page. The label has to be the control, not start
        // like it.
        assertNull(ShareSheet.roleOf("分享你此刻的想法"))
        assertNull(ShareSheet.roleOf("分享到日常"))
        assertNull(ShareSheet.roleOf("分享你的想法"))
    }

    @Test
    fun `the count folded into the label does not hide the control`() {
        // Douyin writes the share count into the same label.
        for (label in listOf("分享，按钮", "分享2，按钮", "分享8，按钮", "分享")) {
            assertEquals(label, Role.SHARE, ShareSheet.roleOf(label))
        }
    }

    @Test
    fun `the sheet's own way out is recognised`() {
        // Douyin's sheet on the study phone carries 取消. Tapping it
        // beats the global BACK, which means whatever the screen it
        // lands on decides -- and being wrong about which screen that
        // is walked two runs out to the search box.
        assertEquals(Role.DISMISS, ShareSheet.roleOf("取消"))
        assertEquals(Role.DISMISS, ShareSheet.roleOf("关闭"))
        assertEquals(Role.DISMISS, ShareSheet.roleOf("Cancel"))
    }

    @Test
    fun `dismissing is never confused with the entry being collected`() {
        // If 取消 were ever read as the copy entry the run would close
        // the sheet and report a link it never copied.
        assertEquals(Role.COPY_LINK, ShareSheet.roleOf("分享链接"))
        assertNull(ShareSheet.roleOf("取消关注"))
        assertNull(ShareSheet.roleOf("关闭AI抖音app引导"))
    }

    @Test
    fun `nothing that acts on another account is ever the share control`() {
        // Every one of these sits in a share sheet next to the entry we
        // do want, and 建群分享, 推荐 and Repost all post something.
        for (label in listOf(
            // Read off Douyin's sheet on the study phone: 合拍 posts a
            // duet with the video, 举报 files a report against it.
            "转发到日常", "推荐", "合拍", "帮上热门", "举报", "取消",
            // Read off Douyin on iOS, which offers a different set.
            "建群分享", "私信",
            "Repost", "Promote", "Create group", "Report", "Not interested",
            "WhatsApp", "SMS", "Instagram Direct", "Facebook",
            "微信", "朋友圈", "QQ", "QQ空间", "微博",
        )) {
            assertNull("$label must not match anything", ShareSheet.roleOf(label))
        }
    }

    @Test
    fun `feed controls next to the share button are not mistaken for it`() {
        for (label in listOf(
            "未点赞，喜欢26，按钮", "评论8，按钮", "未选中，收藏收藏，按钮",
            "音乐，@姐姐创作的原声，按钮", "关注", "播放视频，按钮", "进度条",
            "发布时间：5小时前", "期待你的评论", "返回",
        )) {
            assertNull("$label must not match anything", ShareSheet.roleOf(label))
        }
    }
}

package edu.wellesley.scraper.service

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The 抖音号 pattern and, more importantly, the labels that must never
 * be tapped on the way to it.
 *
 * The avatar beside a Douyin video carries a red `+` follow badge. A
 * tap that lands on it follows the account: an action on someone
 * else's account, taken by software, in a study whose whole claim is
 * that it only observes. The author's `@名字` line opens the same
 * profile and carries no such affordance, so that is what is used --
 * and 关注 is refused outright in case a tree ever puts it where the
 * name should be.
 */
class ProfilePageTest {

    // The app's own functions, not copies of its patterns: a test that
    // re-declares the regex passes whatever the app actually does.
    private fun idIn(text: String) = ProfilePage.douyinIdIn(text)

    private fun isAuthorLink(label: String) = ProfilePage.isAuthorLink(label)

    @Test
    fun `the douyin id is read in the forms the profile uses`() {
        assertEquals("guyue_2024", idIn("抖音号：guyue_2024"))
        assertEquals("guyue_2024", idIn("抖音号: guyue_2024"))
        assertEquals("grape.66", idIn("抖音号 grape.66"))
        assertEquals("a_b-c", idIn("IP属地：北京 抖音号：a_b-c"))
    }

    @Test
    fun `text with no id in it yields nothing`() {
        assertNull(idIn("关注 12  粉丝 3410  获赞 5.2万"))
        assertNull(idIn("今夜的风悄悄月悄悄 吻你的眉梢#lwl"))
    }

    @Test
    fun `the author line is the tap target`() {
        // As the feed renders them, from the study phone.
        assertEquals(true, isAuthorLink("@沽月🦷🍁"))
        assertEquals(true, isAuthorLink("@我爱吃葡萄"))
        assertEquals(true, isAuthorLink("@．．．"))
    }

    @Test
    fun `nothing that follows an account is ever the tap target`() {
        for (label in listOf("关注", "關注", "加关注", "Follow", "follow")) {
            assertEquals("$label must never be tapped", false, isAuthorLink(label))
        }
    }

    @Test
    fun `the profile names itself`() {
        // From the study phone: the nickname is on a node whose
        // contentDescription ends 复制名字. It is the only statement of
        // whose page this is that does not assume the right thing was
        // tapped, which is why it is what gets checked.
        assertEquals("zz7", ProfilePage.profileNameIn("zz7，复制名字"))
        assertEquals("坏了她真可爱", ProfilePage.profileNameIn("坏了她真可爱，复制名字"))
        assertEquals("．．．", ProfilePage.profileNameIn("．．．，复制名字"))
    }

    @Test
    fun `anything else is not a profile name`() {
        for (label in listOf(
            "抖音号：zz272328",
            "220 获赞",
            "复制名字",
            "@zz7",
            "关注",
        )) {
            assertNull("$label read as a profile name", ProfilePage.profileNameIn(label))
        }
    }

    @Test
    fun `a profile is recognised as still covering the feed`() {
        // The screen that ended a run: the id had been read, one BACK
        // had been pressed, and the profile was still up. The next
        // swipe scrolled it, and the run looked for a share sheet on a
        // page that has none.
        for (label in listOf("薄荷骨钉、，复制名字", "抖音号：41435737586")) {
            assertEquals(
                "$label should mark a profile as open",
                true,
                ProfilePage.profileNameIn(label) != null ||
                    ProfilePage.douyinIdIn(label) != null,
            )
        }
    }

    @Test
    fun `the feed does not look like a profile`() {
        for (label in listOf(
            "分享，按钮", "未点赞，喜欢25，按钮", "@薄荷骨钉、", "玩同款", "进度条",
        )) {
            assertEquals(
                "$label read as a profile",
                false,
                ProfilePage.profileNameIn(label) != null ||
                    ProfilePage.douyinIdIn(label) != null,
            )
        }
    }

    @Test
    fun `the video's own back arrow is not the profile's`() {
        // A video opened out of search carries back_btn with the
        // description 返回 at the top left. Looking for "a back arrow"
        // found that one and left the video for the results grid.
        //
        // The pattern cannot tell them apart -- both read 返回 -- so
        // what keeps them apart is when it is consulted: only once a
        // profile has been detected on top. This pins the fact that
        // the label alone proves nothing.
        assertEquals("返回", "返回")
        assertNull(ProfilePage.douyinIdIn("返回"))
        assertNull(ProfilePage.profileNameIn("返回"))
    }

    @Test
    fun `feed controls are not author links`() {
        for (label in listOf(
            "未点赞，喜欢24，按钮",
            "分享，按钮",
            "音乐，@沽月创作的原声，按钮",
            "发布时间：17小时前",
            "玩同款",
        )) {
            assertEquals("$label matched", false, isAuthorLink(label))
        }
    }
}

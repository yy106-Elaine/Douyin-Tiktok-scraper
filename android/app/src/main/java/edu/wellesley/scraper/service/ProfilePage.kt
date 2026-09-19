package edu.wellesley.scraper.service

import android.view.accessibility.AccessibilityNodeInfo

/**
 * Opens an author's profile to read the one identifier Douyin keeps
 * off the feed, and reads it.
 *
 * The feed shows `@昵称`, which is a display name: changeable, and not
 * unique. The 抖音号 is on the profile, one tap away, and it is what
 * still finds an account months later when recruitment happens.
 *
 * **What is tapped matters here more than anywhere else in this app.**
 * The avatar carries a red `+` follow badge, and a tap that lands on
 * it follows the account -- an action on someone else's account, and
 * exactly what this instrument must never take. So the avatar is not
 * used. The `@名字` line under the video opens the same profile and has
 * no follow affordance on it, and the search below refuses any label
 * that looks like a follow control even if it were somehow reached.
 */
object ProfilePage {

    /** The `@名字` under a video. Opens the profile; follows nothing. */
    private val AUTHOR_LINK = Regex("""^@\s*\S""")

    /**
     * Never tapped, whatever else matches. 关注 is the follow button
     * and the badge on the avatar, and both sit beside the author's
     * name in the tree.
     */
    private val NEVER_TAP = Regex("""^(?:关注|關注|加关注|follow)$""", RegexOption.IGNORE_CASE)

    /** The identifier being fetched, as the profile renders it. */
    private val DOUYIN_ID = Regex("""抖音号[：:\s]*([A-Za-z0-9._\-]{2,30})""")

    /**
     * The profile naming itself.
     *
     * Read off the study phone: the nickname sits on a node whose
     * contentDescription is `zz7，复制名字`. It is the only statement of
     * whose page this is that does not depend on having tapped the
     * right thing, which makes it the one worth checking against.
     */
    private val PROFILE_NAME = Regex("""^(.+)[，,]复制名[字稱称]$""")

    /**
     * The 抖音号 in a piece of text, if there is one.
     *
     * Public and pure so the patterns can be checked without a device
     * -- the alternative is a test that re-declares them, which passes
     * whatever the app actually does.
     */
    fun douyinIdIn(text: String): String? = DOUYIN_ID.find(text)?.groupValues?.get(1)

    /**
     * Whether a label is the author line that opens a profile.
     *
     * The negative half is the one that matters: this is what keeps a
     * run from ever pressing 关注.
     */
    fun isAuthorLink(label: String): Boolean =
        !NEVER_TAP.containsMatchIn(label) && AUTHOR_LINK.containsMatchIn(label)

    /** Whose profile this is, according to the page itself. */
    fun profileNameIn(text: String): String? =
        PROFILE_NAME.find(text)?.groupValues?.get(1)?.trim()?.takeIf { it.isNotEmpty() }

    /**
     * The nickname the open profile gives for itself, if it gives one.
     *
     * Null is not "the wrong profile" -- an older build may not label
     * the node at all -- so a caller treats it as "cannot tell" rather
     * than as a mismatch.
     */
    fun openProfileName(roots: List<AccessibilityNodeInfo>): String? {
        for (root in roots) {
            var found: String? = null
            walk(root) { node ->
                val label = label(node) ?: return@walk true
                profileNameIn(label)?.let {
                    found = it
                    return@walk false
                }
                true
            }
            if (found != null) return found
        }
        return null
    }

    /** A profile is open when its own id line is on screen. */
    fun readDouyinId(roots: List<AccessibilityNodeInfo>): String? {
        for (root in roots) {
            var found: String? = null
            walk(root) { node ->
                val label = label(node) ?: return@walk true
                douyinIdIn(label)?.let {
                    found = it
                    return@walk false
                }
                true
            }
            if (found != null) return found
        }
        return null
    }

    /**
     * The `@名字` link for the video **in front**, and the name on it.
     *
     * The qualifier is the whole difficulty. Douyin keeps two or three
     * videos in the tree at once, and taking the first `@` in it opened
     * the neighbour's profile while the run was collecting this video:
     * a 抖音号 read correctly and then filed under someone else's name,
     * which is worse than not reading it -- a wrong association looks
     * exactly like a right one.
     *
     * Screen position is what separates them. The video in front fills
     * the screen and its author line sits near the bottom, above the
     * comment bar; the next video's author line is below the screen
     * edge, and the previous one's is above it. So candidates are
     * filtered to those actually visible and the lowest is taken.
     *
     * @param screenHeight pixels, to tell visible from merely present
     */
    fun findAuthorLink(
        roots: List<AccessibilityNodeInfo>,
        screenHeight: Int,
    ): Pair<AccessibilityNodeInfo, String>? {
        var best: Pair<AccessibilityNodeInfo, String>? = null
        var bestY = Int.MIN_VALUE
        val bounds = android.graphics.Rect()

        for (root in roots) {
            walk(root) { node ->
                val label = label(node) ?: return@walk true
                if (!isAuthorLink(label)) return@walk true
                val target = clickable(node) ?: return@walk true
                if (NEVER_TAP.containsMatchIn(label(target) ?: "")) return@walk true

                target.getBoundsInScreen(bounds)
                val centre = bounds.centerY()
                if (centre in 0..screenHeight && centre > bestY) {
                    bestY = centre
                    best = target to label.removePrefix("@").trim()
                }
                true
            }
        }
        return best
    }

    private fun label(node: AccessibilityNodeInfo): String? {
        val description = node.contentDescription?.toString()?.trim()
        if (!description.isNullOrEmpty()) return description
        return node.text?.toString()?.trim()?.takeIf { it.isNotEmpty() }
    }

    private fun clickable(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        var current: AccessibilityNodeInfo? = node
        var depth = 0
        while (current != null && depth < 4) {
            if (current.isClickable) return current
            current = current.parent
            depth++
        }
        return null
    }

    private fun walk(root: AccessibilityNodeInfo?, visit: (AccessibilityNodeInfo) -> Boolean) {
        if (root == null) return
        val queue = ArrayDeque<Pair<AccessibilityNodeInfo, Int>>()
        queue.add(root to 0)
        var seen = 0
        while (queue.isNotEmpty() && seen < 900) {
            val (node, depth) = queue.removeFirst()
            seen++
            if (!visit(node)) return
            if (depth >= 40) continue
            for (index in 0 until node.childCount) {
                queue.add((node.getChild(index) ?: continue) to depth + 1)
            }
        }
    }
}

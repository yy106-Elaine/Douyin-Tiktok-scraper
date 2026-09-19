package edu.wellesley.scraper.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityNodeInfo
import edu.wellesley.scraper.data.LinkQueue
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.net.SyncWorker
import edu.wellesley.scraper.ui.ClipboardReaderActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Repeats the manual collection step for a bounded stretch of time.
 *
 * The step is: open the share sheet, press "copy link", let the app
 * read the clipboard, close the sheet, scroll to the next video. Doing
 * it by hand costs about four taps per video, which is what caps how
 * much can be collected in a day.
 *
 * Three things keep this honest about what it is.
 *
 * **It is bounded and visible.** A run has a deadline and a video
 * limit, both set when it starts. It stops the moment the foreground
 * app is not the one it was started in, and it can be stopped by hand
 * at any point. It performs no action except the ones a person
 * performs to copy a link, it posts nothing, and it touches no other
 * account.
 *
 * **It stops rather than guesses.** If the share control or the copy
 * entry is not found, the run ends and records what was on screen
 * instead. A loop that keeps tapping when it cannot see what it is
 * tapping is how an automation starts pressing the wrong things.
 *
 * **It has a dry run.** [Mode.DRY_RUN] inspects one screen, reports
 * what the selectors found, and presses nothing. The wording inside
 * the share sheet has never been dumped from a device, so the first
 * run should always be a dry one -- once on a video to check the share
 * control, once with the sheet open to check the copy entry.
 *
 * Every step is recorded in [CaptureStats], so what the run did is
 * readable afterwards rather than inferred.
 */
class AutoCapture(private val service: AccessibilityService) {

    enum class Mode { DRY_RUN, LIVE }

    private val handler = Handler(Looper.getMainLooper())

    /** For the one database write this class makes. */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile
    private var running = false
    private var mode = Mode.DRY_RUN
    private var deadline = 0L
    private var remaining = 0
    private var startedIn: String? = null

    /** The author whose profile is being opened, if one is. */
    private var pendingAuthor: String? = null

    /** Reset by [advance]; see [recover]. */
    private var consecutiveFailures = 0

    /** Consecutive checks finding another app in front; see keepGoing. */
    private var awayReadings = 0

    // What a dry run has seen so far. The share control and the copy
    // entry are never on screen at the same time, so each is kept from
    // whichever look first found it.
    private var sawShare: String? = null
    private var sawCopy: String? = null
    private var tries = 0

    fun isRunning(): Boolean = running

    /**
     * Start a run in the app currently in front.
     *
     * @param minutes how long it may run for
     * @param videos how many videos it may step through
     */
    fun start(mode: Mode, minutes: Int, videos: Int, inPackage: String) {
        if (running) return
        this.mode = mode
        this.deadline = System.currentTimeMillis() + minutes * 60_000L
        this.remaining = videos
        this.startedIn = inPackage
        this.sawShare = null
        this.sawCopy = null
        this.tries = 0
        this.consecutiveFailures = 0
        this.awayReadings = 0
        running = true
        CaptureStats.onAutoStart(mode.name, minutes, videos, inPackage)
        if (mode == Mode.DRY_RUN) {
            handler.postDelayed(::inspect, FIRST_STEP_MILLIS)
        } else {
            handler.postDelayed(::openShare, FIRST_STEP_MILLIS)
        }
    }

    /**
     * Watch for both controls for a while, report what was found, and
     * stop. Pressing nothing.
     *
     * It has to watch rather than glance, because the two controls are
     * never on screen together. The share control is on the feed; the
     * copy entry only exists inside the sheet that opens once the share
     * control is pressed. And a dry run cannot press it -- that is what
     * makes it dry.
     *
     * So: start the run, switch to the app, and open the share sheet by
     * hand while this is watching. It remembers the best it has seen of
     * each, finishes the moment it has both, and otherwise reports at
     * the deadline. A single glance 1.5 seconds after switching apps
     * gave no time to open anything, which made the second half of the
     * check impossible to perform.
     */
    private fun inspect() {
        if (!running) return

        val roots = roots()
        ShareSheet.findShare(roots)?.let { if (sawShare == null) sawShare = it.label }
        ShareSheet.findCopyLink(roots)?.let { if (sawCopy == null) sawCopy = it.label }
        tries++

        val haveBoth = sawShare != null && sawCopy != null
        if (!haveBoth && tries < DRY_TRIES) {
            handler.postDelayed(::inspect, DRY_INTERVAL_MILLIS)
            return
        }

        CaptureStats.onAutoStep("watched for ${tries}s, ${roots.size} window(s) last look")
        CaptureStats.onAutoStep(
            "share control: " + (sawShare?.let { "found \"$it\"" } ?: "NOT FOUND")
        )
        CaptureStats.onAutoStep(
            "copy-link entry: " + (sawCopy?.let { "found \"$it\"" } ?: "NOT FOUND")
        )
        if (!haveBoth) {
            CaptureStats.onAutoFailure(
                "open the share sheet by hand while a dry run is watching; " +
                    "below is the last screen seen",
                ShareSheet.describe(roots),
            )
        }
        stop(if (haveBoth) "dry run finished, both found" else "dry run finished")
    }

    fun stop(why: String) {
        if (!running) return
        running = false
        handler.removeCallbacksAndMessages(null)
        CaptureStats.onAutoStop(why)
    }

    // ----------------------------------------------------------------
    // One video, as four steps on a timer
    // ----------------------------------------------------------------
    //
    // A timer rather than a reaction to accessibility events: the
    // sheet animates, and a step that fires while it is still moving
    // presses whatever happens to be under it. The delays are long
    // enough for the animation, not short enough to race it.

    private fun openShare() {
        if (!keepGoing()) return

        // Nothing is pressed while a panel covers the feed. A run
        // ended up in a comment panel -- the share control underneath
        // is not reachable from there, a swipe scrolls comments, and
        // pressing on is how software starts tapping things nobody
        // chose. Close it first; if it will not close, skip the video.
        if (ShareSheet.isSheetOpen(activeRoots()) ||
            ProfilePage.isProfileOpen(activeRoots())
        ) {
            CaptureStats.onAutoStep("something is covering the feed; closing it")
            closeSheet(0) { closeProfile(0) }
            return
        }

        // Not a feed at all. Swiping a results grid is not collection,
        // and a run that has wandered off the surface it was started
        // on should say so rather than keep going somewhere it was
        // never pointed.
        if (ShareSheet.isSearchResults(roots())) {
            CaptureStats.onAutoFailure(
                "this is the search results page, not a video",
                ShareSheet.describe(roots()),
            )
            stop("left the video feed for the search results")
            return
        }

        val found = ShareSheet.findShare(roots())
        if (found == null) {
            CaptureStats.onAutoFailure(
                "no share control",
                ShareSheet.describe(roots()),
            )
            recover("share control not found")
            return
        }

        CaptureStats.onAutoStep("share: ${found.label}")
        tap(found.node)
        handler.postDelayed(::pressCopyLink, SHEET_OPEN_MILLIS)
    }

    private fun pressCopyLink() {
        if (!keepGoing()) return

        val found = ShareSheet.findCopyLink(roots())
        if (found == null) {
            CaptureStats.onAutoFailure(
                "no copy-link entry",
                ShareSheet.describe(roots()),
            )
            recover("copy-link entry not found")
            return
        }

        CaptureStats.onAutoStep("copy: ${found.label}")
        tap(found.node)
        handler.postDelayed(::readClipboard, COPY_MILLIS)
    }

    private fun readClipboard() {
        if (!keepGoing()) return

        // From Android 10 only a focused app may read the clipboard,
        // so the same translucent activity the floating button uses
        // comes forward for an instant and finishes.
        service.startActivity(
            Intent(service, ClipboardReaderActivity::class.java).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_NO_ANIMATION or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP,
                )
            },
        )
        handler.postDelayed(::nextVideo, CLIPBOARD_MILLIS)
    }

    private fun nextVideo() {
        if (!keepGoing()) return
        waitForApp(0) { closeSheet(0) { visitProfileIfNew() } }
    }

    // ----------------------------------------------------------------
    // The 抖音号, which is not on the feed
    // ----------------------------------------------------------------
    //
    // Douyin shows `@昵称` beside a video and keeps the 抖音号 on the
    // profile. The nickname can change and can be shared; the 抖音号
    // is what still finds the account when recruitment happens months
    // later. So the run opens the profile -- but once per author, not
    // once per video. It belongs to the account, and this is the most
    // expensive step in the loop: roughly fifteen seconds against the
    // nine a video otherwise costs.

    private fun visitProfileIfNew() {
        if (!keepGoing()) return

        val prefs = Prefs(service.applicationContext)
        val found = ProfilePage.findAuthorLink(
            roots(),
            service.resources.displayMetrics.heightPixels,
        )
        val name = found?.second
        if (found == null || name.isNullOrBlank() || name in prefs.visitedAuthors) {
            advance()
            return
        }

        // The name is only ever used to avoid opening the same profile
        // twice. Nothing is filed under it: the 抖音号 is attached to
        // the link just copied, and the link says which video -- and so
        // which author -- it belongs to. An earlier version matched by
        // display name and filed an id under a neighbour's nickname.
        pendingAuthor = name
        CaptureStats.onAutoStep("profile: $name")
        tap(found.first)
        handler.postDelayed(::readDouyinId, PROFILE_OPEN_MILLIS)
    }

    private fun readDouyinId() {
        if (!keepGoing()) return

        val name = pendingAuthor
        pendingAuthor = null
        val prefs = Prefs(service.applicationContext)
        val id = ProfilePage.readDouyinId(roots())

        if (name != null) {
            // Remembered either way. A profile with no id on it will
            // not grow one, and retrying costs the same fifteen
            // seconds every time that author comes round again.
            prefs.visitedAuthors = prefs.visitedAuthors + name
        }
        // The page says whose it is. When it disagrees with the name
        // that was tapped, the run did not land where it meant to and
        // the id would be attached to the wrong video's link. Null
        // means the page did not say, which is not a disagreement.
        val whose = ProfilePage.openProfileName(roots())
        val landedWrong = name != null && whose != null && whose != name

        if (landedWrong) {
            CaptureStats.onAutoStep("discarded $id: opened $whose, wanted $name")
        } else if (id != null) {
            scope.launch {
                val attached = LinkQueue.attachAuthorHandle(
                    service.applicationContext, id
                )
                CaptureStats.onAutoStep(
                    if (attached) "抖音号: $id" else "抖音号 $id has no link to belong to"
                )
                if (attached) SyncWorker.enqueue(service.applicationContext)
            }
        } else {
            CaptureStats.onAutoStep("no 抖音号 on this profile")
        }

        closeProfile(0)
    }

    /**
     * Press BACK until the profile is gone, and check rather than
     * assume.
     *
     * One BACK and a fixed pause left it open: the next swipe scrolled
     * the profile, and the run then looked for a share sheet on a page
     * that has none and stopped. Same shape as [closeSheet] -- press
     * only while something is detected, so a BACK never reaches the
     * feed itself and walks out of Douyin.
     */
    private fun closeProfile(attempt: Int) {
        if (!keepGoing()) return

        // Wait for the video to come back, and recognise it by the
        // share control being there again -- not by the profile
        // appearing to be gone. A closing window lingers in the window
        // list for a moment, so "still open" read true when it was
        // already closing, a second BACK went in, and that one left
        // the video entirely and landed on the search results.
        //
        // Exactly one BACK, then wait. Pressing again to hurry a page
        // that is already leaving is what walked the run out of the
        // feed, and there is nothing to hurry towards: the next step
        // is a swipe.
        if (onAVideo()) {
            advance()
            return
        }
        if (attempt == 0) {
            dismissWhatIsOnTop()
            handler.postDelayed({ closeProfile(1) }, PROFILE_BACK_MILLIS)
            return
        }
        if (attempt < PROFILE_WAIT_TRIES) {
            handler.postDelayed({ closeProfile(attempt + 1) }, PROFILE_BACK_MILLIS)
            return
        }
        recover("the profile did not close")
    }

    /**
     * BACK, unless we are already looking at a video.
     *
     * One invariant, in one place: if the feed's own share control is
     * on screen then nothing is covering it, and BACK there does not
     * dismiss anything -- it leaves the video. Repeatedly, it leaves
     * for the results page and then the search box, which is exactly
     * where two runs ended up.
     *
     * Every BACK in this class goes through here, so the rule cannot
     * be forgotten at one of the call sites later.
     */
    /**
     * Dismiss whatever is on top, using that thing's own control.
     *
     * The control is chosen by what is detected, never searched for
     * on its own. A video opened out of search has its own 返回 at the
     * top left, and looking for "a back arrow" found that one and
     * left the video -- the page it went back to was the results
     * grid, which is exactly the sideways movement this loop must not
     * make.
     *
     * So: a sheet is closed by the sheet's 取消, a profile by the
     * profile's 返回, and when neither is detected nothing is pressed
     * at all. The global BACK remains only for a sheet or profile
     * that offers no control of its own, because there it can only
     * dismiss the thing we have already established is covering the
     * screen.
     */
    private fun dismissWhatIsOnTop(): Boolean {
        val top = activeRoots()

        if (ShareSheet.isSheetOpen(top)) {
            ShareSheet.findDismiss(top)?.let {
                CaptureStats.onAutoStep("dismiss: ${it.label}")
                tap(it.node)
                return true
            }
            CaptureStats.onAutoStep("closing the sheet with back")
            service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
            return true
        }

        if (ProfilePage.isProfileOpen(top)) {
            ProfilePage.findBack(top)?.let {
                CaptureStats.onAutoStep("back arrow on the profile")
                tap(it)
                return true
            }
            CaptureStats.onAutoStep("leaving the profile with back")
            service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
            return true
        }

        CaptureStats.onAutoStep("nothing on top to dismiss")
        return false
    }

    /** Nothing of ours is covering the feed. */
    private fun onAVideo(): Boolean {
        // "What is covering the screen" is a question about the window
        // on top, not about every window the app has. A closed window
        // lingers in the list for a while, so asking all of them kept
        // answering "the profile is still open" after the back arrow
        // had already closed it -- and the recovery for that pressed
        // back again, which is what left the video.
        val top = activeRoots()
        if (top.isEmpty()) return false
        if (ProfilePage.isProfileOpen(top)) return false
        if (ShareSheet.isSheetOpen(top)) return false
        // Not "the share control is findable". A video whose controls
        // have not drawn yet is still a video, and treating it as not
        // one sent the loop into recovery on a screen that needed
        // nothing done to it.
        return !ShareSheet.isSearchResults(top)
    }

    /**
     * The window on top, when it belongs to the app being collected.
     *
     * [roots] answers "what does this app have open"; this answers
     * "what is the person looking at". Those are different questions
     * and confusing them has now caused the same failure three times.
     */
    private fun activeRoots(): List<AccessibilityNodeInfo> {
        val wanted = startedIn
        val active = service.windows
            .filter { it.isActive }
            .mapNotNull { window ->
                window.root?.takeIf { it.packageName?.toString() == wanted }
            }
        if (active.isNotEmpty()) return active
        val root = service.rootInActiveWindow
        return if (root?.packageName?.toString() == wanted) listOf(root) else emptyList()
    }

    /**
     * Wait for the app being collected from to be in front again.
     *
     * Reading the clipboard brings this app's own activity forward, and
     * it stays there until its upload finishes -- seconds, on a slow
     * connection. Pressing BACK then would close that activity and
     * cancel the save; swiping then would swipe over this app. So the
     * next step waits for the feed rather than assuming it.
     */
    private fun waitForApp(attempt: Int, then: () -> Unit) {
        if (!keepGoing()) return
        if (frontPackage() == startedIn) {
            then()
            return
        }
        if (attempt >= RETURN_TRIES) {
            CaptureStats.onAutoFailure(
                "${startedIn ?: "the app"} did not come back to the front",
                ShareSheet.describe(roots()),
            )
            stop("did not return to ${startedIn ?: "the app"}")
            return
        }
        CaptureStats.onAutoStep("waiting for ${startedIn ?: "the app"}")
        handler.postDelayed({ waitForApp(attempt + 1, then) }, SETTLE_MILLIS)
    }

    /**
     * Press BACK until no sheet is covering the feed, and no more.
     *
     * Douyin opens two sheets for one copy: 分享给, then 链接已复制成功.
     * One BACK leaves the first still up, and a swipe then scrolls the
     * sheet rather than the feed. Pressing BACK a fixed number of times
     * is worse: a BACK that reaches the feed itself leaves Douyin, and
     * the run would be walking backwards out of the app it is reading.
     */
    private fun closeSheet(attempt: Int, then: () -> Unit) {
        if (!keepGoing()) return

        // Stop on the video being back, not on the sheet appearing to
        // be gone: a closing window is still listed for a moment, and
        // the extra BACK that buys goes through the feed.
        if (onAVideo()) {
            then()
            return
        }
        if (attempt >= CLOSE_TRIES) {
            recover("the share sheet would not close")
            return
        }
        dismissWhatIsOnTop()
        handler.postDelayed({ closeSheet(attempt + 1, then) }, BACK_MILLIS)
    }

    private fun advance() {
        remaining--
        consecutiveFailures = 0
        CaptureStats.onAutoStep("next video, $remaining left")
        swipeUp()
        handler.postDelayed(::openShare, SETTLE_MILLIS)
    }

    /**
     * Give up on this video, not on the run.
     *
     * A thirty-minute session ended on its third video because a
     * profile had not closed in time. One step going wrong is not
     * evidence that the next will, and ending the session costs every
     * video that would have followed.
     *
     * It is still bounded, and still does not guess. Recovery is the
     * same BACK-until-clear the loop already uses, then a swipe -- no
     * new taps, nothing pressed that was not identified. What is
     * guarded against is a run that fails on every video and keeps
     * going regardless, so three in a row with nothing collected
     * between them stops it and records the screen.
     */
    private fun recover(why: String) {
        consecutiveFailures++
        if (consecutiveFailures >= MAX_FAILURES) {
            CaptureStats.onAutoFailure(
                "$why, and $consecutiveFailures in a row",
                ShareSheet.describe(roots()),
            )
            stop(why)
            return
        }
        CaptureStats.onAutoStep("$why -- skipping this video")
        // BACK only to dismiss something that is demonstrably there.
        dismissWhatIsOnTop()
        handler.postDelayed({
            if (!keepGoing()) return@postDelayed
            remaining--
            swipeUp()
            handler.postDelayed(::openShare, SETTLE_MILLIS)
        }, BACK_MILLIS)
    }

    // ----------------------------------------------------------------
    // Guards
    // ----------------------------------------------------------------

    /** False, and stops the run, when any bound has been reached. */
    private fun keepGoing(): Boolean {
        if (!running) return false
        if (remaining <= 0) {
            stop("video limit reached")
            return false
        }
        if (System.currentTimeMillis() >= deadline) {
            stop("time limit reached")
            return false
        }
        // The app in front must still be the one the run started in.
        // Anything else means a notification, a phone call, or the
        // person navigating away -- none of which should be tapped on.
        val front = frontPackage()
        // This app's own clipboard reader comes forward on purpose for
        // every video, so its being in front is part of the loop, not
        // someone walking away. Nothing is ever pressed there: roots()
        // only ever returns windows belonging to startedIn.
        if (front != startedIn && front != service.packageName) {
            awayReadings++
            // One reading is not evidence that someone left. A
            // thirty-minute session ended after six videos because the
            // launcher was reported for an instant while a profile was
            // closing. Nothing is pressed meanwhile -- this returns
            // false either way, so no step acts while another app is
            // in front -- but the run waits to see it again before
            // giving up on the other twenty-nine minutes.
            if (awayReadings >= AWAY_READINGS) {
                stop("left ${startedIn ?: "the app"} (now ${front ?: "nothing"})")
            } else {
                CaptureStats.onAutoStep("${front ?: "something else"} is in front; waiting")
                // Exactly one chain, always. This check runs at the
                // top of every step, so scheduling a resume without
                // cancelling first queued a second openShare beside
                // the one already pending -- two chains pressing BACK
                // and tapping out of order, which walked the run out
                // of the video, into the results page and then into
                // the search box. Whatever was pending is abandoned;
                // this becomes the only thing waiting to happen.
                handler.removeCallbacksAndMessages(null)
                handler.postDelayed(::openShare, SETTLE_MILLIS)
            }
            return false
        }
        awayReadings = 0
        return true
    }

    /**
     * Which app is in front, preferring the active window and falling
     * back to whichever window the system marks active.
     *
     * `rootInActiveWindow` goes null for a moment during a transition,
     * and reading that as "the person left" ends a run that is fine.
     */
    private fun frontPackage(): String? =
        service.rootInActiveWindow?.packageName?.toString()
            ?: service.windows.firstOrNull { it.isActive }?.root?.packageName?.toString()

    /**
     * Every window belonging to the app the run started in.
     *
     * Not `rootInActiveWindow`: Douyin's comment input is its own
     * window, and while it holds focus that call returns three nodes
     * with the entire feed -- share control included -- in a window it
     * does not mention. A dry run reported both controls missing that
     * way while they were on screen the whole time.
     *
     * Windows from any other app are left out rather than searched, so
     * a notification banner or another app's overlay is never a place
     * this looks for something to press.
     */
    private fun roots(): List<AccessibilityNodeInfo> {
        val wanted = startedIn
        val out = service.windows.mapNotNull { window ->
            window.root?.takeIf { it.packageName?.toString() == wanted }
        }
        if (out.isNotEmpty()) return out
        // getWindows() can come back empty right after a transition.
        val active = service.rootInActiveWindow
        return if (active?.packageName?.toString() == wanted) listOf(active) else emptyList()
    }

    private fun tap(node: AccessibilityNodeInfo) {
        if (!node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            CaptureStats.onAutoStep("tap refused by the view")
        }
    }

    /** A short upward swipe: one video in a vertical feed. */
    private fun swipeUp() {
        val metrics = service.resources.displayMetrics
        val x = metrics.widthPixels / 2f
        val path = Path().apply {
            moveTo(x, metrics.heightPixels * 0.72f)
            lineTo(x, metrics.heightPixels * 0.28f)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, SWIPE_MILLIS)
        service.dispatchGesture(
            GestureDescription.Builder().addStroke(stroke).build(),
            null,
            null,
        )
    }

    private companion object {
        /** Long enough for the person to take their hand off the screen. */
        const val FIRST_STEP_MILLIS = 1_500L

        // The rest are animation budgets, not throttling: each step
        // has to land after the previous one has finished drawing.
        const val SHEET_OPEN_MILLIS = 1_400L
        const val COPY_MILLIS = 900L
        const val CLIPBOARD_MILLIS = 1_200L
        const val BACK_MILLIS = 700L
        const val SETTLE_MILLIS = 1_600L
        const val SWIPE_MILLIS = 250L

        /** ~10s for the clipboard upload to finish and the feed to return. */
        const val RETURN_TRIES = 6

        /** Douyin stacks two sheets; three presses is one spare. */
        const val CLOSE_TRIES = 3

        // A profile is a page load, not an animation, so these are
        // generous. Only a first sighting of an author pays them.
        const val PROFILE_OPEN_MILLIS = 2_500L
        const val PROFILE_BACK_MILLIS = 1_200L

        /** Consecutive failed videos before the run is the problem. */
        const val MAX_FAILURES = 3

        /** One BACK, then this many waits for the feed to return. */
        const val PROFILE_WAIT_TRIES = 6

        /**
         * Consecutive readings of another app in front before the run
         * accepts that someone walked away. About five seconds, and
         * nothing is pressed during any of them.
         */
        const val AWAY_READINGS = 3

        // A dry run watches for half a minute: long enough to switch
        // apps, find the video again and open the share sheet by hand.
        const val DRY_TRIES = 30
        const val DRY_INTERVAL_MILLIS = 1_000L
    }
}

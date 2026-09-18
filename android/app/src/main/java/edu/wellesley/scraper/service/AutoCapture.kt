package edu.wellesley.scraper.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityNodeInfo
import edu.wellesley.scraper.ui.ClipboardReaderActivity

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

    @Volatile
    private var running = false
    private var mode = Mode.DRY_RUN
    private var deadline = 0L
    private var remaining = 0
    private var startedIn: String? = null

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
        running = true
        CaptureStats.onAutoStart(mode.name, minutes, videos, inPackage)
        if (mode == Mode.DRY_RUN) {
            handler.postDelayed(::inspect, FIRST_STEP_MILLIS)
        } else {
            handler.postDelayed(::openShare, FIRST_STEP_MILLIS)
        }
    }

    /**
     * Report what the selectors find on the screen as it is now, and
     * stop. Pressing nothing.
     *
     * A dry run cannot walk the loop, because after the first step it
     * would be looking for a "copy link" entry on a feed with no sheet
     * open. So it inspects one screen: run it on a video to check the
     * share control, then open the share sheet by hand and run it
     * again to check the copy entry. Two runs, and the selectors are
     * either confirmed or the report says what was there instead.
     */
    private fun inspect() {
        val roots = roots()
        val share = ShareSheet.findShare(roots)
        val copy = ShareSheet.findCopyLink(roots)

        CaptureStats.onAutoStep("looked in ${roots.size} window(s)")
        CaptureStats.onAutoStep("share sheet open: ${ShareSheet.isSheetOpen(roots)}")

        CaptureStats.onAutoStep(
            "share control: " + (share?.let { "found \"${it.label}\"" } ?: "NOT FOUND")
        )
        CaptureStats.onAutoStep(
            "copy-link entry: " + (copy?.let { "found \"${it.label}\"" } ?: "NOT FOUND")
        )
        if (share == null || copy == null) {
            CaptureStats.onAutoFailure(
                "see the screen below; run this on a video, then again with the " +
                    "share sheet open",
                ShareSheet.describe(roots),
            )
        }
        stop("dry run finished")
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

        val found = ShareSheet.findShare(roots())
        if (found == null) {
            CaptureStats.onAutoFailure(
                "no share control",
                ShareSheet.describe(roots()),
            )
            stop("share control not found")
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
            stop("copy-link entry not found")
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
        waitForApp(0) { closeSheet(0) }
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
    private fun closeSheet(attempt: Int) {
        if (!keepGoing()) return

        if (!ShareSheet.isSheetOpen(roots())) {
            advance()
            return
        }
        if (attempt >= CLOSE_TRIES) {
            CaptureStats.onAutoFailure(
                "the share sheet would not close",
                ShareSheet.describe(roots()),
            )
            stop("share sheet would not close")
            return
        }
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        handler.postDelayed({ closeSheet(attempt + 1) }, BACK_MILLIS)
    }

    private fun advance() {
        remaining--
        CaptureStats.onAutoStep("next video, $remaining left")
        swipeUp()
        handler.postDelayed(::openShare, SETTLE_MILLIS)
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
            stop("left ${startedIn ?: "the app"} (now ${front ?: "nothing"})")
            return false
        }
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
    }
}

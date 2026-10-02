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

    /**
     * A run reads one of two surfaces.
     *
     * [DRY_RUN] and [LIVE] work a vertical feed: the post fills the
     * screen and the next one is a swipe away. [GRID_DRY_RUN] and
     * [GRID] work Douyin's search results, where 图文 posts live --
     * there the next post is a cell to open, and getting back out is
     * part of the loop. See [SearchGrid].
     */
    enum class Mode { DRY_RUN, LIVE, GRID_DRY_RUN, GRID }

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

    /**
     * Cells already opened, by their own text; see [SearchGrid].
     *
     * Kept for the length of a run and no longer. Coming back out of
     * a post does not always restore the scroll offset, so an index
     * would re-open the same cell and never reach the next one.
     */
    private val opened = mutableSetOf<String>()

    /** Consecutive scrolls of the grid that turned up nothing new. */
    private var barrenScrolls = 0

    /** How tall a card is here, so a scroll can move by one row. */
    private var cardHeight = 0

    /**
     * BACK presses since the run was last home on the grid.
     *
     * Counted across calls, not per call: the step that waits for the
     * app to come back schedules a fresh attempt, and a per-call
     * counter starts at zero each time -- so a run that could not
     * find its way home pressed BACK for as long as it was allowed,
     * out of the post, out of the search, through the recommended
     * feed and finally out of Douyin onto the home screen.
     *
     * But *since last home*, not for the whole run. Counting every
     * press a run ever makes caps the run itself: a healthy post
     * costs one press on the way out, so a thirty-minute pass over
     * three hundred posts needs three hundred of them. Counted for
     * the run, it collected nine posts and stopped on its own
     * allowance.
     *
     * A run that is lost does not become less lost by pressing more.
     * A run that keeps arriving is not lost.
     */
    private var backPresses = 0

    /** Whether this run reads the results grid rather than a feed. */
    private val onGrid: Boolean
        get() = mode == Mode.GRID || mode == Mode.GRID_DRY_RUN

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
        this.opened.clear()
        this.barrenScrolls = 0
        this.backPresses = 0
        running = true
        CaptureStats.onAutoStart(mode.name, minutes, videos, inPackage)
        handler.postDelayed(
            {
                when (mode) {
                    Mode.DRY_RUN -> inspect()
                    Mode.GRID_DRY_RUN -> inspectGrid()
                    Mode.GRID -> openTile()
                    Mode.LIVE -> openShare()
                }
            },
            FIRST_STEP_MILLIS,
        )
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

        val roots = everywhere()
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
                    "below is the last screen seen, with what carries " +
                    "text first and what can be tapped after it",
                ShareSheet.describe(roots, limit = 20) +
                    ShareSheet.describeControls(roots, limit = 30),
            )
        }
        stop(if (haveBoth) "dry run finished, both found" else "dry run finished")
    }

    /**
     * Report what the results grid looks like, and press nothing.
     *
     * No wording on this surface has ever been dumped from a device,
     * so this is the first thing to run: stand on the search results
     * with the 图文 tab showing and read back what the selectors
     * found. A cell whose label is a like count or a tab name is a
     * selector to fix before anything is tapped, not after.
     */
    private fun inspectGrid() {
        if (!running) return

        if (!onTheGrid()) {
            CaptureStats.onAutoFailure(
                "this is not the search results page (the tab strip and " +
                    "two cards have to be on it) -- below is what was on " +
                    "screen instead",
                SearchGrid.describe(activeRoots()),
            )
            stop("dry run finished, not on the grid")
            return
        }

        // A dry run reports what it refused as well as what it kept.
        // The first one offered a like button and a timestamp as
        // cells to open, and neither was visible in a list of what
        // had been accepted.
        val refused = mutableListOf<String>()
        val metrics = service.resources.displayMetrics
        val tiles = SearchGrid.tiles(
            activeRoots(), metrics.widthPixels, metrics.heightPixels,
        ) { refused.add(it) }
        CaptureStats.onAutoStep("grid: ${tiles.size} cell(s) readable")
        tiles.take(DRY_TILES).forEach {
            CaptureStats.onAutoStep("cell ${it.width}x${it.height}: ${it.label}")
        }
        refused.distinct().take(DRY_TILES).forEach {
            CaptureStats.onAutoStep("refused -- $it")
        }
        if (tiles.isEmpty()) {
            CaptureStats.onAutoFailure(
                "no cells found on the grid",
                SearchGrid.describe(activeRoots()),
            )
        }
        stop("dry run finished, ${tiles.size} cell(s)")
    }

    /**
     * Open the next cell that has not been opened yet.
     *
     * Nothing is tapped unless the grid is the screen in front: every
     * other state -- a post still open, a sheet still up -- is handled
     * by getting back to the grid first, because a tap aimed at a cell
     * that lands on something else is the failure this whole class is
     * written to avoid.
     */
    private fun openTile() {
        if (!keepGoing()) return

        if (!onTheGrid()) {
            // Before the first cell there is nothing to come back
            // from, so there is nothing to press either: the run was
            // started on whatever page the person was standing on,
            // and if that is not the grid the answer is to say so.
            if (opened.isEmpty()) {
                CaptureStats.onAutoFailure(
                    "a 图文 run has to start on the search results, with " +
                        "the tab strip and a full row of cards on screen. " +
                        "Nothing was pressed",
                    SearchGrid.describe(activeRoots()),
                )
                stop("not started on the search results")
                return
            }
            backToGrid(0)
            return
        }

        // The window on top, not every window the app has open. The
        // results page stays listed behind an opened post, so cells
        // read off `roots()` can belong to a page nobody is looking
        // at -- and a tap then lands on whatever is in front of it.
        val tiles = gridTiles(activeRoots())
        val index = SearchGrid.pick(tiles.map { it.label }, opened)
        if (index == null) {
            // Everything on screen has been done. Scrolling is the
            // only movement this loop makes on the grid, and a scroll
            // that turns up nothing new twice running means the list
            // has ended or stopped loading.
            if (barrenScrolls >= BARREN_SCROLLS) {
                CaptureStats.onAutoStep("no new cells after $barrenScrolls scroll(s)")
                stop("the grid ran out of new posts")
                return
            }
            barrenScrolls++
            CaptureStats.onAutoStep("scrolling the grid")
            scrollGrid()
            handler.postDelayed(::openTile, SETTLE_MILLIS)
            return
        }

        barrenScrolls = 0
        tiles.maxOfOrNull { it.height }?.let { if (it > 0) cardHeight = it }
        val tile = tiles[index]
        // Marked before the tap, not after. A cell that fails to open
        // has to be stepped over, or the run spends the rest of its
        // deadline tapping the same broken one.
        opened.add(tile.label)
        CaptureStats.onAutoStep("open: ${tile.label}")
        tap(tile.node)
        handler.postDelayed({ waitForCaption(0) }, POST_OPEN_MILLIS)
    }

    /**
     * The results page, on its own evidence; see [SearchGrid.isGrid].
     *
     * Asked of the window on top rather than of every window the app
     * has open. A post opened out of the results keeps the results
     * page listed behind it, and answering this off that background
     * window is how a run came to tap a post believing it was a grid.
     */
    private fun onTheGrid(): Boolean {
        val metrics = service.resources.displayMetrics
        return SearchGrid.isGrid(
            activeRoots(), metrics.widthPixels, metrics.heightPixels,
        )
    }

    private fun gridTiles(
        roots: List<AccessibilityNodeInfo>,
    ): List<SearchGrid.Tile> {
        val metrics = service.resources.displayMetrics
        return SearchGrid.tiles(roots, metrics.widthPixels, metrics.heightPixels)
    }

    /**
     * Come back out of a post to the grid, and check rather than
     * assume.
     *
     * The same shape as [closeProfile]: press only while something is
     * detected to be covering the grid, then wait and look again. On
     * this surface BACK is the way out -- a post opened from search
     * goes back to the results it was opened from -- which is the
     * movement the feed loop must never make and the only one this
     * loop lives on.
     *
     * **BACK needs evidence that we are inside something**, not
     * merely the absence of evidence that we are home. The first
     * version pressed it whenever the grid was not recognised, and a
     * results page one card short of the threshold is not recognised
     * -- so a run standing on the results pressed BACK its way out of
     * the search, which is what a person watching saw as "it went
     * backwards". The tab strip is the evidence: it is on the results
     * page and on no post, so when it is there and the grid still does
     * not qualify, the answer is to say so and stop.
     */
    private fun backToGrid(attempt: Int) {
        if (!keepGoing()) return

        if (onTheGrid()) {
            // Home. Whatever it took to get here is spent, and the
            // next post starts with a full allowance.
            backPresses = 0
            handler.postDelayed(::openTile, SETTLE_MILLIS)
            return
        }

        val top = activeRoots()
        val covered = ShareSheet.isSheetOpen(top) || ProfilePage.isProfileOpen(top)
        if (!covered && SearchGrid.hasTabStrip(top)) {
            CaptureStats.onAutoFailure(
                "this looks like the results page, but fewer than two " +
                    "cells are readable on it -- scroll it so a full row " +
                    "of cards is on screen and start again. Nothing was " +
                    "pressed",
                SearchGrid.describe(top),
            )
            stop("on the results page with nothing readable to open")
            return
        }
        if (attempt >= BACK_TO_GRID_TRIES) {
            CaptureStats.onAutoFailure(
                "could not get back to the search results",
                SearchGrid.describe(roots()),
            )
            stop("lost the search results")
            return
        }
        backPresses++
        if (backPresses > MAX_BACK_PRESSES) {
            CaptureStats.onAutoFailure(
                "pressed back $backPresses times in a row without reaching " +
                    "the search results -- stopping rather than pressing on",
                SearchGrid.describe(activeRoots()),
            )
            stop("too many back presses")
            return
        }
        // A sheet or a profile is dismissed by its own control; a post
        // has none of ours on it, so BACK is what leaves it.
        if (!dismissWhatIsOnTop()) {
            CaptureStats.onAutoStep("leaving the post with back ($backPresses)")
            service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        }
        handler.postDelayed({ backToGrid(attempt + 1) }, BACK_MILLIS)
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
        CaptureStats.onAutoStep("looking for the share control")
        if (!keepGoing()) {
            CaptureStats.onAutoStep("share: not going on")
            return
        }

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

        // On a grid run the results page is home, not a wrong turn:
        // the post was closed earlier than expected, so take the next
        // cell rather than stopping.
        if (onGrid && onTheGrid()) {
            CaptureStats.onAutoStep("back on the grid already")
            openTile()
            return
        }

        // Not a feed at all. Swiping a results grid is not collection,
        // and a run that has wandered off the surface it was started
        // on should say so rather than keep going somewhere it was
        // never pointed.
        //
        // The grid's own test, not "is there a search box": a video
        // opened out of the results keeps the search box in its
        // window tree, so a feed run started on such a video stopped
        // on its first step with "this is the search results page" --
        // on a video that was plainly playing. The strict test wants
        // the tab strip and a row of cards too, and a post has
        // neither.
        if (!onGrid && onTheGrid()) {
            CaptureStats.onAutoFailure(
                "this is the search results page, not a video",
                ShareSheet.describe(roots()),
            )
            stop("left the video feed for the search results")
            return
        }

        val found = ShareSheet.findShare(everywhere())
        if (found == null) {
            // Both lists: what carries text, and what can be tapped.
            // On a 图文 the share control is an icon with no label, so
            // the text-only dump said nothing about the one thing
            // that was missing.
            CaptureStats.onAutoFailure(
                "no share control",
                ShareSheet.describe(roots(), limit = 20) +
                    ShareSheet.describeControls(roots(), limit = 30),
            )
            recover("share control not found")
            return
        }

        CaptureStats.onAutoStep("share: ${found.label}")
        tap(found.node)
        handler.postDelayed({ pressCopyLink(0) }, SHEET_OPEN_MILLIS)
    }

    /**
     * Press the entry that puts the link on the clipboard, once it is
     * there to press.
     *
     * Polled rather than looked for once. The single shot was timed
     * against Douyin, whose sheet is drawn and populated almost
     * immediately. TikTok's is a friend list -- names, avatars, a
     * search box -- and it is not finished 1.4 seconds after the tap.
     * A run on TikTok therefore looked for 复制链接 before it existed,
     * gave the video up, and left the half-drawn sheet covering the
     * feed; the next video's share control was underneath it, so the
     * next two videos failed too and the run stopped having collected
     * nothing. The sheet was in the failure dump with 复制链接 plainly
     * in it.
     *
     * Polling costs Douyin nothing: the entry is there on the first
     * look, and the wait only elapses where the entry never appears.
     */
    private fun pressCopyLink(tries: Int) {
        if (tries == 0) CaptureStats.onAutoStep("looking for the copy entry")
        if (!keepGoing()) {
            CaptureStats.onAutoStep("copy: not going on")
            return
        }

        val found = ShareSheet.findCopyLink(everywhere())
        if (found == null) {
            if (tries < COPY_LINK_TRIES) {
                handler.postDelayed({ pressCopyLink(tries + 1) }, SHEET_POLL_MILLIS)
                return
            }
            CaptureStats.onAutoFailure(
                "no copy-link entry",
                ShareSheet.describe(roots(), limit = 20) +
                    ShareSheet.describeControls(roots(), limit = 30),
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
        // Never on a grid run. Getting back out of a post to the grid
        // is already one return trip per post; adding a profile makes
        // it two nested ones, and the way back from the second is
        // ambiguous -- BACK from a profile opened inside a post may
        // land on the post or on the grid. The 抖音号 for a note is
        // better fetched from the link afterwards than guessed at by
        // pressing BACK and hoping.
        if (onGrid) {
            advance()
            return
        }
        // Off unless asked for. Collecting a link never leaves the
        // video; opening a profile does, and getting back from one is
        // the only thing in this loop that has ever gone wrong. The
        // 抖音号 is worth having, but not at the price of a run that
        // wanders into the search results.
        if (!prefs.visitProfiles) {
            advance()
            return
        }
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

    /**
     * Nothing is covering the page the run works from.
     *
     * Two surfaces, two answers. On a feed the question is "is a
     * video back", and the results page counts as "no" because a run
     * that reached it has gone somewhere it should not be. On the
     * grid a post is where the run is *supposed* to be, and the
     * results page is home -- so asking [onAVideo] there would answer
     * no on both, and the sheet-closing loop would press BACK its
     * full three times on a page with nothing to close. Two of those
     * go through the post and out of the search results.
     */
    private fun coverCleared(): Boolean {
        if (!onGrid) return onAVideo()
        val top = activeRoots()
        if (top.isEmpty()) return false
        return !ShareSheet.isSheetOpen(top) && !ProfilePage.isProfileOpen(top)
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
        //
        // And not "is there a search box", for the reason in
        // `openShare`: a video reached through search carries one.
        val metrics = service.resources.displayMetrics
        return !SearchGrid.isGrid(top, metrics.widthPixels, metrics.heightPixels)
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
        if (attempt == 0) CaptureStats.onAutoStep("waiting for the sheet to clear")
        if (!keepGoing()) return

        // Stop on the cover being gone, not on the sheet appearing to
        // be gone: a closing window is still listed for a moment, and
        // the extra BACK that buys goes through the feed.
        if (coverCleared()) {
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
        CaptureStats.onAutoStep("next post, $remaining left")
        if (onGrid) {
            backToGrid(0)
            return
        }
        swipeUp()
        handler.postDelayed({ waitForCaption(0) }, SETTLE_MILLIS)
    }

    /**
     * Let the post's text draw before covering it with a sheet.
     *
     * The share sheet is opened about a second and a half after the
     * swipe, and it hides the feed for the rest of the video. If the
     * caption has not rendered in that window it is never read: a
     * thirty-minute run collected 174 links and 45 captions.
     *
     * A caption cannot be recovered afterwards. The video id can --
     * the link is followed later and yields it, along with the exact
     * publication time -- but the text on the screen exists only
     * while the screen shows it. So this waits, and gives up after a
     * few seconds because some posts genuinely have no caption.
     */
    private fun waitForCaption(attempt: Int) {
        if (attempt == 0) CaptureStats.onAutoStep("waiting for the caption")
        if (!keepGoing()) {
            CaptureStats.onAutoStep("caption wait: not going on")
            return
        }
        val screenHeight = service.resources.displayMetrics.heightPixels
        if (attempt >= CAPTION_TRIES ||
            ShareSheet.captionHasDrawn(everywhere(), screenHeight)
        ) {
            openShare()
            return
        }
        handler.postDelayed({ waitForCaption(attempt + 1) }, CAPTION_WAIT_MILLIS)
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
    /**
     * Give up on this video without touching anything.
     *
     * Six builds went into making the loop press its way back to a
     * video after something went wrong, and every one of them found a
     * new way to press too much: an extra BACK, two chains pressing at
     * once, the video's own 返回 mistaken for a profile's. The presses
     * were never the recovery -- they were the failure.
     *
     * So recovery presses nothing. If a video is on screen the run
     * swipes to the next one, which is the only movement this loop is
     * supposed to make. If a video is not on screen the run stops and
     * records what was there, because whatever else is showing, the
     * answer is not for software to start pressing things to find out.
     */
    private fun recover(why: String) {
        consecutiveFailures++

        if (onGrid) {
            if (consecutiveFailures >= MAX_FAILURES) {
                CaptureStats.onAutoFailure(
                    "$why, and $consecutiveFailures in a row",
                    SearchGrid.describe(activeRoots()),
                )
                stop(why)
                return
            }
            // The cell is already marked opened, so going back to the
            // grid steps over it rather than retrying it.
            CaptureStats.onAutoStep("$why -- skipping this post")
            remaining--
            backToGrid(0)
            return
        }

        if (!onAVideo()) {
            CaptureStats.onAutoFailure(
                "$why, and this is not a video",
                ShareSheet.describe(activeRoots()),
            )
            stop(why)
            return
        }
        if (consecutiveFailures >= MAX_FAILURES) {
            CaptureStats.onAutoFailure(
                "$why, and $consecutiveFailures in a row",
                ShareSheet.describe(activeRoots()),
            )
            stop(why)
            return
        }

        CaptureStats.onAutoStep("$why -- skipping this video")
        remaining--
        swipeUp()
        handler.postDelayed({ waitForCaption(0) }, SETTLE_MILLIS)
    }

    // ----------------------------------------------------------------
    // Guards
    // ----------------------------------------------------------------

    /** False, and stops the run, when any bound has been reached. */
    private fun keepGoing(): Boolean {
        // Every refusal says why. The one silent return here -- the
        // run having been stopped -- left a 图文 run looking as though
        // it had simply decided to stop halfway through a post, with
        // fifty-six seconds of nothing in the log and no way to tell
        // which step had given up.
        if (!running) {
            CaptureStats.onAutoStep("step reached after the run stopped")
            return false
        }
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
                handler.postDelayed(
                    { if (onGrid) openTile() else openShare() },
                    SETTLE_MILLIS,
                )
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
    /**
     * Everywhere a control might be: the window in front, then the
     * rest of the app's.
     *
     * These are not the same list, and on a 图文 they do not overlap.
     * A dry run standing on a post with nothing pressed reported one
     * window -- and its contents were the share sheet's entries
     * (转发到日常, 分享链接, 推荐, 合拍, 帮上热门, 举报), which Douyin
     * keeps in the tree before anyone opens it. The post itself, with
     * its share control on it, was not in that list at all; it was in
     * the active window, where a grid dry run had dumped it in full
     * at the same moment.
     *
     * So the search for the share control, run over `roots()`, was
     * looking through a hidden panel and never at the page. It found
     * the copy entry -- that one *is* in the panel -- and no share
     * control, every time, which is exactly the failure that made the
     * whole 图文 surface look broken.
     *
     * The window in front comes first, because that is where a
     * person's next tap would land.
     */
    private fun everywhere(): List<AccessibilityNodeInfo> =
        activeRoots() + roots()

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

    /**
     * Move the grid on by about one row.
     *
     * Not [swipeUp], which is written for a feed: it covers nearly
     * half the screen in a quarter of a second, and a grid reads that
     * as a fling. A run watching four cards at a time scrolled past
     * several rows in one go, and the posts in between were never
     * opened -- invisibly, because a skipped card leaves no trace.
     *
     * So: the height of a card as last measured, a little over, and
     * slowly enough that the list stops where it is put rather than
     * carrying on under its own momentum.
     */
    private fun scrollGrid() {
        val metrics = service.resources.displayMetrics
        val height = metrics.heightPixels.toFloat()
        val step = (
            if (cardHeight > 0) cardHeight * ROW_OVERLAP else height * 0.33f
            ).coerceAtMost(height * 0.45f)
        val x = metrics.widthPixels / 2f
        val from = height * 0.70f
        val path = Path().apply {
            moveTo(x, from)
            lineTo(x, (from - step).coerceAtLeast(height * 0.08f))
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, GRID_SWIPE_MILLIS)
        service.dispatchGesture(
            GestureDescription.Builder().addStroke(stroke).build(),
            null,
            null,
        )
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

        /**
         * How long to keep looking for the copy-link entry, as
         * (tries x interval) after the first look above.
         *
         * ~6s in total. Generous because the cost of being early is
         * not one lost video but three: the sheet stays open over the
         * feed, and the failures that follow are the run's own.
         */
        const val SHEET_POLL_MILLIS = 400L
        const val COPY_LINK_TRIES = 12
        const val COPY_MILLIS = 900L
        const val CLIPBOARD_MILLIS = 1_200L
        const val BACK_MILLIS = 700L
        const val SETTLE_MILLIS = 1_600L
        const val SWIPE_MILLIS = 250L

        /**
         * A grid scroll is slow on purpose: the same distance thrown
         * quickly is a fling, and a fling skips rows.
         */
        const val GRID_SWIPE_MILLIS = 700L

        /** A little more than one card, so no row lands half on screen. */
        const val ROW_OVERLAP = 1.15f

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

        /**
         * Up to three more seconds waiting for a caption to draw.
         *
         * Paid only by posts whose text is slow or absent, and worth
         * it: a caption not read is gone, where a video id missed now
         * is recovered from the link later.
         */
        const val CAPTION_TRIES = 6
        const val CAPTION_WAIT_MILLIS = 500L

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

        /** Cells a grid dry run lists, so the log stays readable. */
        const val DRY_TILES = 8

        /**
         * A post opened from the grid is a page load, not an
         * animation: its caption has further to come than a feed
         * post's, which is already half-drawn behind the one in front.
         */
        const val POST_OPEN_MILLIS = 2_000L

        /** One BACK per try, waiting for the results to come back. */
        const val BACK_TO_GRID_TRIES = 6

        /**
         * BACK presses allowed between one arrival on the grid and
         * the next. A post costs one on the way out and occasionally
         * two; past this many in a row the run is lost, and a lost
         * run presses nothing.
         */
        const val MAX_BACK_PRESSES = 6

        /**
         * Scrolls of the grid that turn up nothing new before the run
         * accepts that the list has ended. Two, because the first
         * scroll after a long run of opened cells can land on a row
         * that is still loading its labels.
         */
        const val BARREN_SCROLLS = 2
    }
}

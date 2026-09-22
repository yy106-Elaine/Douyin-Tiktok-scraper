package edu.wellesley.scraper.service

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import edu.wellesley.scraper.data.CaptureDatabase
import edu.wellesley.scraper.data.CaptureEntity
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.net.SyncWorker
import edu.wellesley.scraper.parser.DouyinParser
import edu.wellesley.scraper.parser.IdScanner
import edu.wellesley.scraper.parser.NodeTools
import edu.wellesley.scraper.parser.ParsedPost
import edu.wellesley.scraper.parser.PostParser
import edu.wellesley.scraper.parser.TikTokParser
import edu.wellesley.scraper.parser.TikTokSearchParser
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Calendar

/**
 * Reads Douyin and TikTok off the screen -- both the feed and, where a
 * keyword study samples from, the search results grid.
 *
 * Two limits decide what can be read. The system delivers events only
 * for the packages declared in `accessibility_service_config.xml`, and
 * every frame is checked to belong to one of them before it is read.
 * The second check is not redundant: an event names the app that
 * produced it, not the window on top, and a live session captured the
 * task switcher that way.
 */
class CaptureAccessibilityService : AccessibilityService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val buffer = CaptureBuffer()
    private val idleHandler = Handler(Looper.getMainLooper())

    /** Reads the search grid; see where it is consulted below. */
    private val searchParser = TikTokSearchParser()

    /**
     * Shown only while a target app is in front, so it is never
     * floating over anything unrelated.
     */
    private val saveButton by lazy { SaveLinkButton(this) }

    /**
     * Repeats the copy-link step for a bounded stretch. Idle unless
     * started from the app, and it stops itself; see AutoCapture.
     */
    private val auto by lazy { AutoCapture(this) }

    /** A run requested from the app, waiting for a target app in front. */
    private data class Armed(val mode: AutoCapture.Mode, val minutes: Int, val videos: Int)

    /** What a run is doing, for the app to show and to enable buttons by. */
    enum class State { SERVICE_OFF, IDLE, ARMED, RUNNING }

    @Volatile
    private var armed: Armed? = null

    private val parsers: Map<String, PostParser> = mapOf(
        "com.ss.android.ugc.aweme" to DouyinParser(),
        "com.ss.android.ugc.aweme.lite" to DouyinParser(),
        "com.zhiliaoapp.musically" to TikTokParser(),
        "com.tiktok.lite.go" to TikTokParser(),
    )

    private var lastScanAt = 0L
    private var lastPackage: String? = null

    /** Most recently observed feed tab; see where it is read below. */
    private var lastFeed: String? = null

    /**
     * Finalises the buffer when the screen goes quiet.
     *
     * Restricting `packageNames` means no event ever arrives for any
     * other app, so leaving Douyin or TikTok is invisible to this
     * service -- there is no "user switched away" signal to flush on.
     * Without this timer the posts still buffered when someone closes
     * the app are never written at all.
     */
    private val idleFlush = Runnable { flush(force = true) }

    override fun onServiceConnected() {
        super.onServiceConnected()
        CaptureStats.onServiceConnected()
        instance = this
    }

    companion object {
        /** Feeds repaint constantly; one read every half second is plenty. */
        private const val SCAN_INTERVAL_MILLIS = 500L

        /** Slightly longer than the buffer's own settle window. */
        private const val IDLE_FLUSH_MILLIS = 6_000L

        /**
         * The live service, so the app can start and stop an assisted
         * run. Null whenever the service is off, which is the only
         * state in which a run cannot be started -- deliberately, since
         * a run needs to read the screen to know what it is pressing.
         */
        @Volatile
        private var instance: CaptureAccessibilityService? = null

        fun isConnected(): Boolean = instance != null

        fun isRunning(): Boolean = instance?.auto?.isRunning() == true

        /**
         * Arm a run, to begin once Douyin or TikTok is in front.
         *
         * It cannot start immediately: the app that is in front when
         * the button is pressed is this one. So the service holds the
         * request and starts on the first frame from a target app,
         * which is also the point at which there is a video on screen
         * to find a share control on. Returns why not, or null.
         */
        fun armAssisted(mode: AutoCapture.Mode, minutes: Int, videos: Int): String? {
            val service = instance ?: return "Turn on the capture service first"
            if (service.auto.isRunning()) return "A run is already going"
            service.armed = Armed(mode, minutes, videos)
            CaptureStats.onAutoStep("armed: ${mode.name}, waiting for the app")
            return null
        }

        fun stopAssisted() {
            instance?.armed = null
            instance?.auto?.stop("stopped by hand")
        }

        /** What a run is doing, in the four words the app can show. */
        fun runState(): State {
            val service = instance ?: return State.SERVICE_OFF
            return when {
                service.auto.isRunning() -> State.RUNNING
                service.armed != null -> State.ARMED
                else -> State.IDLE
            }
        }
    }

    /**
     * Never let a read throw out of here.
     *
     * An exception in this callback kills the process, which takes the
     * accessibility service and the overlay button down with it and
     * leaves collection silently dead until someone re-enables the
     * service. Most of the parsing below is written against interfaces
     * that change without notice, so one bad frame must cost that frame
     * and nothing more.
     */
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        try {
            handleEvent(event)
        } catch (error: Exception) {
            CaptureStats.onSkip(
                event?.packageName?.toString() ?: "?",
                "error: ${error.javaClass.simpleName}: ${error.message?.take(80)}",
            )
        }
    }

    private fun handleEvent(event: AccessibilityEvent?) {
        val eventPackage = event?.packageName?.toString() ?: return
        if (eventPackage !in parsers.keys) return

        idleHandler.removeCallbacks(idleFlush)
        idleHandler.postDelayed(idleFlush, IDLE_FLUSH_MILLIS)

        val now = System.currentTimeMillis()
        if (now - lastScanAt < SCAN_INTERVAL_MILLIS) return
        lastScanAt = now

        // An event's package name says which app produced the event, not
        // which window is currently on top: an event can arrive from the
        // feed while rootInActiveWindow has already moved on to the task
        // switcher or a notification shade. Reading that window would
        // both store nonsense and observe apps this service has no
        // business seeing, so the window's own package has to agree.
        val root = rootInActiveWindow
        if (root == null) {
            CaptureStats.onSkip(eventPackage, "no active window")
            return
        }
        val activePackage = root.packageName?.toString()
        // Trust the window over the event for which parser to use.
        val parser = parsers[activePackage]
        if (activePackage == null || parser == null) {
            CaptureStats.onSkip(eventPackage, "active window is $activePackage")
            saveButton.hide()
            return
        }
        lastPackage = activePackage
        if (Prefs(applicationContext).showSaveButton) saveButton.show()

        // A run armed from the app starts here, on the first frame
        // from a target app -- which is also the first moment there is
        // a video on screen to find a share control on.
        armed?.let { request ->
            armed = null
            auto.start(request.mode, request.minutes, request.videos, activePackage)
        }

        val nodes = NodeTools.flatten(root)
        if (nodes.isEmpty()) {
            CaptureStats.onSkip(activePackage, "window returned no nodes")
            return
        }
        // A search results grid holds many posts at once and is the
        // surface a keyword study samples from, so it is read whole and
        // before the feed parser gets a look at it.
        if (searchParser.recognises(nodes)) {
            val found = searchParser.parseAll(nodes)
            CaptureStats.onFrame(activePackage, nodes.size, found.size)
            CaptureStats.onSearchFrame(found.size)
            // The search grid is a different surface from the feed and
            // may expose what the feed does not, so it gets scanned
            // too. Returning early without this left the question of
            // whether ids appear here unmeasured.
            CaptureStats.onIdScan(
                activePackage,
                IdScanner.describe(nodes),
                IdScanner.scan(nodes).isNotEmpty(),
            )
            CaptureStats.onFrameDump(nodes)
            found.forEach {
                CaptureStats.onParsed(it)
                buffer.observe(it)
            }
            CaptureStats.distinctPosts = buffer.size()
            flush(force = false)
            return
        }

        parser.skipReason(nodes)?.let { reason ->
            CaptureStats.onSkip(activePackage, reason)
            CaptureLog.skipped(reason)
            return
        }

        // The feed tab belongs to the screen, not to any one post -- and
        // TikTok hides the tab bar while a video plays fullscreen, so it
        // is absent from most frames. The last tab actually observed is
        // carried forward: someone stays on a tab for many posts, so the
        // most recent reading is the best available answer. Recorded as
        // "last observed", not as certainty.
        parser.feed(nodes)?.let { lastFeed = it }
        val feed = lastFeed
        val segments = NodeTools.segment(nodes, parser::isPostBoundary)
        CaptureStats.onFrame(activePackage, nodes.size, segments.size)
        CaptureLog.segments(segments.size, nodes.size)

        // Whether either app puts a video id on screen decides how links
        // can be obtained at all, so record the answer per frame.
        val scanned = IdScanner.scan(nodes)
        CaptureStats.onIdScan(activePackage, IdScanner.describe(nodes), scanned.isNotEmpty())
        CaptureStats.onFrameDump(nodes)

        var parsedAny = false
        for (segment in segments) {
            // Reported and buffered as the same object. The self-check
            // used to print the post before the feed was attached, so
            // "Last parsed" said `feed=null` on every run while the
            // stored row had the tab or the search term on it -- which
            // reads as the one field failing, and on TikTok that field
            // is the sampling frame.
            val post = (parser.parse(segment) ?: continue).copy(feed = feed)
            parsedAny = true
            CaptureStats.onParsed(post)
            CaptureLog.parsed(post)
            buffer.observe(post)
        }
        if (!parsedAny) {
            CaptureStats.onNothingParsed(nodes)
            CaptureLog.dumpUnparsed(nodes)
        }
        CaptureStats.distinctPosts = buffer.size()

        flush(force = false)
    }

    override fun onInterrupt() {
        flush(force = true)
    }

    override fun onDestroy() {
        auto.stop("service stopped")
        instance = null
        saveButton.hide()
        idleHandler.removeCallbacks(idleFlush)
        flush(force = true)
        scope.cancel()
        super.onDestroy()
    }

    private fun flush(force: Boolean) {
        val settled = buffer.drain(force)
        if (settled.isEmpty()) return

        val packageName = lastPackage ?: return
        scope.launch {
            val dao = CaptureDatabase.get(applicationContext).captureDao()
            var stored = 0
            var duplicates = 0
            for ((post, capturedAt) in settled) {
                val fingerprint = post.fingerprint() ?: continue
                if (dao.countSince(fingerprint, startOfDay(capturedAt)) > 0) {
                    duplicates++
                    continue
                }
                dao.insert(
                    CaptureEntity(
                        platformPackage = packageName,
                        fingerprint = fingerprint,
                        capturedAt = capturedAt,
                        payloadJson = payloadJson(post),
                    )
                )
                stored++
                CaptureStats.lastFingerprint = fingerprint
            }
            CaptureStats.onStored(stored, duplicates)
            if (stored > 0 && Prefs(applicationContext).isRegistered) {
                SyncWorker.enqueue(applicationContext)
            }
        }
    }

    private fun payloadJson(post: ParsedPost): String {
        val json = JSONObject()
        for ((key, value) in post.toPayload()) {
            if (value != null) json.put(key, value)
        }
        return json.toString()
    }

    private fun startOfDay(millis: Long): Long = Calendar.getInstance().apply {
        timeInMillis = millis
        set(Calendar.HOUR_OF_DAY, 0)
        set(Calendar.MINUTE, 0)
        set(Calendar.SECOND, 0)
        set(Calendar.MILLISECOND, 0)
    }.timeInMillis
}

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
import edu.wellesley.scraper.parser.NodeTools
import edu.wellesley.scraper.parser.ParsedPost
import edu.wellesley.scraper.parser.PostParser
import edu.wellesley.scraper.parser.TikTokParser
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Calendar

/**
 * Reads Douyin and TikTok feeds off the screen.
 *
 * The system only delivers events for the packages declared in
 * `accessibility_service_config.xml`, so this service is structurally
 * incapable of observing any other app.
 */
class CaptureAccessibilityService : AccessibilityService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val buffer = CaptureBuffer()
    private val idleHandler = Handler(Looper.getMainLooper())

    private val parsers: Map<String, PostParser> = mapOf(
        "com.ss.android.ugc.aweme" to DouyinParser(),
        "com.ss.android.ugc.aweme.lite" to DouyinParser(),
        "com.zhiliaoapp.musically" to TikTokParser(),
        "com.tiktok.lite.go" to TikTokParser(),
    )

    private var lastScanAt = 0L
    private var lastPackage: String? = null

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
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val packageName = event?.packageName?.toString() ?: return
        val parser = parsers[packageName] ?: return
        lastPackage = packageName

        idleHandler.removeCallbacks(idleFlush)
        idleHandler.postDelayed(idleFlush, IDLE_FLUSH_MILLIS)

        val now = System.currentTimeMillis()
        if (now - lastScanAt < SCAN_INTERVAL_MILLIS) return
        lastScanAt = now

        val nodes = NodeTools.flatten(rootInActiveWindow)
        if (nodes.isEmpty()) {
            CaptureStats.onSkip(packageName, "screen returned no nodes")
            return
        }
        if (parser.shouldSkip(nodes)) {
            CaptureStats.onSkip(packageName, "comment sheet open")
            CaptureLog.skipped("comment sheet open")
            return
        }

        // The feed tab belongs to the screen, not to any one post.
        val feed = parser.feed(nodes)
        val segments = NodeTools.segment(nodes, parser::isPostBoundary)
        CaptureStats.onFrame(packageName, nodes.size, segments.size)
        CaptureLog.segments(segments.size, nodes.size)

        var parsedAny = false
        for (segment in segments) {
            val post = parser.parse(segment) ?: continue
            parsedAny = true
            CaptureStats.onParsed(post)
            CaptureLog.parsed(post)
            buffer.observe(post.copy(feed = feed))
        }
        if (!parsedAny) {
            CaptureStats.onNothingParsed(nodes)
            CaptureLog.dumpUnparsed(nodes)
        }

        flush(force = false)
    }

    override fun onInterrupt() {
        flush(force = true)
    }

    override fun onDestroy() {
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

    private companion object {
        /** Feeds repaint constantly; one read every half second is plenty. */
        const val SCAN_INTERVAL_MILLIS = 500L

        /** Slightly longer than the buffer's own settle window. */
        const val IDLE_FLUSH_MILLIS = 6_000L
    }
}

package edu.wellesley.scraper.service

import android.accessibilityservice.AccessibilityService
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

    private val parsers: Map<String, PostParser> = mapOf(
        "com.ss.android.ugc.aweme" to DouyinParser(),
        "com.ss.android.ugc.aweme.lite" to DouyinParser(),
        "com.zhiliaoapp.musically" to TikTokParser(),
        "com.tiktok.lite.go" to TikTokParser(),
    )

    private var lastScanAt = 0L
    private var lastPackage: String? = null

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val packageName = event?.packageName?.toString() ?: return
        val parser = parsers[packageName]

        if (parser == null) {
            // Left a target app: finalise whatever is still buffered.
            if (lastPackage != null) flush(force = true)
            lastPackage = null
            return
        }
        lastPackage = packageName

        val now = System.currentTimeMillis()
        if (now - lastScanAt < SCAN_INTERVAL_MILLIS) return
        lastScanAt = now

        val nodes = NodeTools.flatten(rootInActiveWindow)
        if (nodes.isEmpty() || parser.shouldSkip(nodes)) return

        // The feed tab belongs to the screen, not to any one post.
        val feed = parser.feed(nodes)
        for (segment in NodeTools.segment(nodes, parser::isPostBoundary)) {
            parser.parse(segment)?.let { buffer.observe(it.copy(feed = feed)) }
        }
        flush(force = false)
    }

    override fun onInterrupt() {
        flush(force = true)
    }

    override fun onDestroy() {
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
            for ((post, capturedAt) in settled) {
                val fingerprint = post.fingerprint() ?: continue
                if (dao.countSince(fingerprint, startOfDay(capturedAt)) > 0) continue
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
    }
}

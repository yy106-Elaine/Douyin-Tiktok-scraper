package edu.wellesley.scraper.service

import edu.wellesley.scraper.parser.FlatNode
import edu.wellesley.scraper.parser.ParsedPost
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Live self-check state, readable from the app's own screen.
 *
 * The accessibility service runs in this same process, so a singleton
 * is enough to get its state in front of someone holding the phone.
 * That matters because every failure here is silent: a service that was
 * never enabled, a parser whose selectors no longer match, and a guard
 * that skips every frame all look identical from the outside -- zero
 * rows -- and telling them apart otherwise means a USB cable and adb.
 */
object CaptureStats {

    @Volatile var serviceConnectedAt: Long? = null
    @Volatile var lastEventAt: Long? = null
    @Volatile var lastPackage: String? = null
    @Volatile var lastNodeCount: Int = 0
    @Volatile var lastSegmentCount: Int = 0
    @Volatile var framesSeen: Int = 0
    @Volatile var framesSkipped: Int = 0
    @Volatile var lastSkipReason: String? = null
    @Volatile var parsedTotal: Int = 0
    @Volatile var storedTotal: Int = 0
    @Volatile var duplicateTotal: Int = 0
    @Volatile var lastParsed: String? = null
    @Volatile var lastUnparsedDump: List<String> = emptyList()

    /** What the passive id scan found on the last screen read. */
    @Volatile var lastIdScan: String? = null
    @Volatile var idsFoundTotal: Int = 0

    fun onServiceConnected() {
        serviceConnectedAt = System.currentTimeMillis()
    }

    fun onIdScan(summary: String, found: Boolean) {
        lastIdScan = summary
        if (found) idsFoundTotal++
    }

    fun onFrame(packageName: String, nodeCount: Int, segmentCount: Int) {
        lastEventAt = System.currentTimeMillis()
        lastPackage = packageName
        lastNodeCount = nodeCount
        lastSegmentCount = segmentCount
        framesSeen++
    }

    fun onSkip(packageName: String, reason: String) {
        lastEventAt = System.currentTimeMillis()
        lastPackage = packageName
        lastSkipReason = reason
        framesSkipped++
    }

    fun onParsed(post: ParsedPost) {
        parsedTotal++
        lastParsed = "handle=${post.authorHandle} name=${post.authorName} " +
            "likes=${post.likeRaw} " +
            "comments=${post.commentRaw} shares=${post.shareRaw} " +
            "saves=${post.saveRaw} feed=${post.feed} " +
            "caption=${post.caption?.take(30)}"
    }

    fun onStored(count: Int, duplicates: Int) {
        storedTotal += count
        duplicateTotal += duplicates
    }

    /** Text-bearing nodes from a frame that produced no post. */
    fun onNothingParsed(nodes: List<FlatNode>) {
        lastUnparsedDump = nodes
            .filter { it.text != null || it.description != null }
            .take(40)
            .map {
                "id=${it.viewId?.substringAfterLast('/') ?: "-"} | " +
                    "text=${it.text?.take(40) ?: "-"} | " +
                    "desc=${it.description?.take(40) ?: "-"}"
            }
    }

    /** A block of text someone can read on screen, or paste into a message. */
    fun report(): String {
        val lines = mutableListOf<String>()

        lines += if (serviceConnectedAt == null) {
            "Capture service: NOT RUNNING\n" +
                "  Turn it on under Accessibility > Installed apps.\n" +
                "  Android 13+ needs Apps > Video Capture > ⋮ >\n" +
                "  Allow restricted settings first."
        } else {
            "Capture service: running since ${time(serviceConnectedAt)}"
        }

        lines += ""
        lines += "Frames read: $framesSeen   skipped: $framesSkipped"
        if (lastEventAt == null) {
            lines += "No screens seen yet."
            lines += "  If the service is running, open Douyin or TikTok."
        } else {
            lines += "Last screen: ${lastPackage ?: "?"} at ${time(lastEventAt)}"
            lines += "  $lastNodeCount nodes -> $lastSegmentCount post(s)"
        }
        lastSkipReason?.let { lines += "Last skip: $it" }

        lines += ""
        lines += "Posts parsed: $parsedTotal"
        lines += "Rows stored: $storedTotal   same-day repeats: $duplicateTotal"
        lastParsed?.let { lines += "Last parsed:\n  $it" }

        lines += ""
        lines += "Video ids seen on screen: $idsFoundTotal of $framesSeen frames"
        lastIdScan?.let { lines += "  last scan: $it" }

        if (lastUnparsedDump.isNotEmpty()) {
            lines += ""
            lines += "Last screen that parsed nothing:"
            lastUnparsedDump.forEach { lines += "  $it" }
        }

        return lines.joinToString("\n")
    }

    private fun time(millis: Long?): String =
        if (millis == null) "never"
        else SimpleDateFormat("HH:mm:ss", Locale.US).format(Date(millis))
}

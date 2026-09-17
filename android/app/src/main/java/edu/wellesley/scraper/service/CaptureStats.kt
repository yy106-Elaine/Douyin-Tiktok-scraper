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
    @Volatile var lastFrameDump: List<String> = emptyList()
    @Volatile var lastSelectedNodes: List<String> = emptyList()
    @Volatile var distinctPosts: Int = 0

    /**
     * Fingerprint of the most recently stored post.
     *
     * A link copied out of the app moments later belongs to this post,
     * so sending it along makes the pairing exact instead of a guess
     * against a time window.
     */
    @Volatile var lastFingerprint: String? = null

    /** Search-grid frames read, and tiles harvested from them. */
    @Volatile var searchFrames: Int = 0
    @Volatile var searchTiles: Int = 0

    fun onSearchFrame(tiles: Int) {
        searchFrames++
        searchTiles += tiles
    }

    /** What the passive id scan found on the last screen read. */
    @Volatile var lastIdScan: String? = null
    @Volatile var idsFoundTotal: Int = 0

    /**
     * Frames read and ids found, per app.
     *
     * Douyin and TikTok are separate implementations, so a result from
     * one says nothing about the other. Reporting them together hid
     * that every frame so far had come from TikTok, and an app with no
     * row here simply has not been measured.
     */
    private val framesByPackage = LinkedHashMap<String, Int>()
    private val idsByPackage = LinkedHashMap<String, Int>()

    fun onServiceConnected() {
        serviceConnectedAt = System.currentTimeMillis()
    }

    fun onIdScan(summary: String, found: Boolean) {
        lastIdScan = summary
        if (found) idsFoundTotal++
    }

    @Synchronized
    fun onIdScan(packageName: String, summary: String, found: Boolean) {
        onIdScan(summary, found)
        framesByPackage[packageName] = (framesByPackage[packageName] ?: 0) + 1
        if (found) idsByPackage[packageName] = (idsByPackage[packageName] ?: 0) + 1
    }

    @Synchronized
    private fun idScanByPackage(): List<String> = framesByPackage.map { (pkg, frames) ->
        "  $pkg: ${idsByPackage[pkg] ?: 0} of $frames frames"
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
        lastUnparsedDump = dump(nodes)
    }

    /**
     * Every read frame is dumped, not only the ones that fail.
     *
     * Once parsing succeeds a failure dump never fires again, which is
     * exactly when the fields that are still empty -- saves, feed,
     * handle -- become impossible to fix without guessing. Keeping the
     * last successful frame means the real nodes are one button away.
     */
    fun onFrameDump(nodes: List<FlatNode>) {
        lastFrameDump = dump(nodes)
        lastSelectedNodes = nodes
            .filter { it.selected }
            .take(8)
            .map { "selected: text=${it.text ?: "-"} desc=${it.description ?: "-"}" }
    }

    private fun dump(nodes: List<FlatNode>): List<String> = nodes
        .filter { it.text != null || it.description != null }
        .take(60)
        .map {
            "id=${it.viewId?.substringAfterLast('/') ?: "-"} | " +
                "text=${it.text?.take(50) ?: "-"} | " +
                "desc=${it.description?.take(50) ?: "-"}" +
                (it.extras?.let { extra -> " | extras=${extra.take(60)}" } ?: "") +
                if (it.selected) " | SELECTED" else ""
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
        lines += "Video ids seen on screen, per app:"
        val perApp = idScanByPackage()
        if (perApp.isEmpty()) lines += "  nothing scanned yet"
        lines += perApp
        lastIdScan?.let { lines += "  last scan: $it" }

        lines += "Distinct posts buffered: $distinctPosts"
        lines += "Search frames: $searchFrames   tiles harvested: $searchTiles"

        if (lastSelectedNodes.isNotEmpty()) {
            lines += ""
            lines += "Nodes marked selected:"
            lastSelectedNodes.forEach { lines += "  $it" }
        }

        if (lastUnparsedDump.isNotEmpty()) {
            lines += ""
            lines += "Last screen that parsed nothing:"
            lastUnparsedDump.forEach { lines += "  $it" }
        }

        if (lastFrameDump.isNotEmpty()) {
            lines += ""
            lines += "Last screen read (${lastFrameDump.size} text nodes):"
            lastFrameDump.forEach { lines += "  $it" }
        }

        return lines.joinToString("\n")
    }

    private fun time(millis: Long?): String =
        if (millis == null) "never"
        else SimpleDateFormat("HH:mm:ss", Locale.US).format(Date(millis))
}

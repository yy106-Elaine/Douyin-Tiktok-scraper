package edu.wellesley.scraper.service

import android.util.Log
import edu.wellesley.scraper.BuildConfig
import edu.wellesley.scraper.parser.FlatNode
import edu.wellesley.scraper.parser.ParsedPost

/**
 * Calibration logging, debug builds only.
 *
 * Selectors fail silently: an app update leaves the service running and
 * the fields empty. Watching this log next to the phone is the fastest
 * way to tell "parsed nothing" from "parsed the wrong thing", and the
 * node dump gives the view ids and descriptions to write new selectors
 * against without a separate `uiautomator dump`.
 *
 *     adb logcat -s VideoCapture
 */
object CaptureLog {

    private const val TAG = "VideoCapture"
    private const val MAX_DUMPED_NODES = 60

    val enabled: Boolean get() = BuildConfig.DEBUG

    fun parsed(post: ParsedPost) {
        if (!enabled) return
        Log.d(
            TAG,
            "parsed ${post.platform} author=${post.authorHandle} " +
                "likes=${post.likeRaw} comments=${post.commentRaw} " +
                "shares=${post.shareRaw} saves=${post.saveRaw} " +
                "feed=${post.feed} music=${post.music} " +
                "caption=${post.caption?.take(40)}",
        )
    }

    fun skipped(reason: String) {
        if (enabled) Log.d(TAG, "frame skipped: $reason")
    }

    fun segments(count: Int, nodeCount: Int) {
        if (enabled) Log.d(TAG, "screen: $nodeCount nodes -> $count post(s)")
    }

    /**
     * Dump the nodes a parser could not make sense of. Only text-bearing
     * nodes are shown -- the rest are layout containers and add noise.
     */
    fun dumpUnparsed(nodes: List<FlatNode>) {
        if (!enabled) return
        val interesting = nodes.filter { it.text != null || it.description != null }
        Log.d(TAG, "--- no post parsed; ${interesting.size} text nodes ---")
        for (node in interesting.take(MAX_DUMPED_NODES)) {
            Log.d(
                TAG,
                "  id=${node.viewId?.substringAfterLast('/')} " +
                    "text=${node.text?.take(50)} desc=${node.description?.take(50)}",
            )
        }
        if (interesting.size > MAX_DUMPED_NODES) {
            Log.d(TAG, "  ... ${interesting.size - MAX_DUMPED_NODES} more")
        }
    }
}

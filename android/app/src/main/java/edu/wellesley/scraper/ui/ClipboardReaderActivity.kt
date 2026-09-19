package edu.wellesley.scraper.ui

import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import edu.wellesley.scraper.R
import edu.wellesley.scraper.data.LinkQueue
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.net.SyncWorker
import edu.wellesley.scraper.service.CaptureStats
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Reads the clipboard and saves whatever link is in it, then closes.
 *
 * From Android 10 the clipboard is readable only by an app that holds
 * window focus, so an activity has to come forward for an instant to do
 * it. This one is translucent, keeps no history and finishes
 * immediately, so the system returns to whatever was underneath -- the
 * link gets recorded without leaving the app being worked in.
 *
 * The read happens in [onWindowFocusChanged], not in onCreate. Being
 * created is not the same as holding focus, and reading too early
 * returns an empty clipboard and reports "nothing copied" for a link
 * that was copied a second earlier.
 *
 * Reached from the floating button, so the sequence is: share, copy
 * link, tap. Nothing here touches the other app's interface; the
 * copying is a person's action and this only picks up the result.
 *
 * A ComponentActivity, not an AppCompatActivity: AppCompat requires a
 * Theme.AppCompat descendant and throws on creation otherwise. With the
 * translucent system theme this activity needs, that crash took the
 * whole process down -- and the accessibility service and its overlay
 * button with it, which is why the button vanished for good on the
 * first tap. Nothing here draws a view, so AppCompat buys nothing.
 */
class ClipboardReaderActivity : ComponentActivity() {

    private var handled = false

    /** How many times the clipboard has been re-read this visit. */
    private var waited = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        overridePendingTransition(0, 0)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus || handled) return
        handled = true
        saveClipboard()
    }

    /**
     * Put the clipboard on the queue and close, without waiting for the
     * upload.
     *
     * This used to post the link and finish only once the server had
     * answered, which meant an assisted run stood still for the length
     * of a round trip on every video -- and lost the link outright if
     * the round trip failed. The queue is on disk, so closing early
     * costs nothing: the upload runs in the background and retries.
     */
    private fun saveClipboard() {
        val prefs = Prefs(this)
        if (!prefs.isRegistered) {
            finishWith(getString(R.string.share_not_registered))
            return
        }

        val text = clipboardText()
        if (text.isNullOrEmpty()) {
            finishWith(getString(R.string.clipboard_empty))
            return
        }
        // The clipboard still holding the previous video's link means
        // the copy has not landed yet, not that the same video came
        // round twice. Reading it then loses a video silently: the
        // queue sees text it already has, drops it, and the run moves
        // on. Five copies produced four links that way. So wait for it
        // to change, briefly, before believing it.
        if (text == prefs.lastSavedClipboard && waited < MAX_WAITS) {
            waited++
            CaptureStats.onClipboardWait()
            window.decorView.postDelayed({ saveClipboard() }, WAIT_MILLIS)
            return
        }

        val fingerprint = CaptureStats.lastFingerprint
        lifecycleScope.launch {
            val queued = withContext(Dispatchers.IO) {
                LinkQueue.add(
                    context = applicationContext,
                    rawText = text,
                    sharedAt = System.currentTimeMillis(),
                    fingerprint = fingerprint,
                ).also { CaptureStats.onLinkQueued(LinkQueue.waiting(applicationContext)) }
            }
            if (queued == LinkQueue.Queued.ADDED) SyncWorker.enqueue(applicationContext)
            finishWith(
                getString(
                    when (queued) {
                        LinkQueue.Queued.ADDED -> R.string.clipboard_saved
                        LinkQueue.Queued.ALREADY_HAVE_IT -> R.string.clipboard_already_saved
                        LinkQueue.Queued.EMPTY -> R.string.clipboard_empty
                    }
                )
            )
        }
    }

    private fun clipboardText(): String? {
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        return clipboard.primaryClip
            ?.takeIf { it.itemCount > 0 }
            ?.getItemAt(0)
            ?.coerceToText(this)
            ?.toString()
            ?.trim()
    }

    private companion object {
        // Two seconds in total. Long enough for a share sheet to put
        // a link on the clipboard, short enough that the run's next
        // step is not left waiting on a copy that failed outright.
        const val MAX_WAITS = 10
        const val WAIT_MILLIS = 200L
    }

    private fun finishWith(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
        finish()
        overridePendingTransition(0, 0)
    }
}

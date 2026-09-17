package edu.wellesley.scraper.ui

import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import edu.wellesley.scraper.R
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.net.ApiClient
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

    private fun saveClipboard() {
        val prefs = Prefs(this)
        val apiKey = prefs.apiKey
        if (apiKey == null) {
            finishWith(getString(R.string.share_not_registered))
            return
        }

        val text = clipboardText()
        if (text.isNullOrEmpty()) {
            finishWith(getString(R.string.clipboard_empty))
            return
        }
        if (text == prefs.lastSavedClipboard) {
            finishWith(getString(R.string.clipboard_already_saved))
            return
        }

        val fingerprint = CaptureStats.lastFingerprint
        lifecycleScope.launch {
            val message = try {
                withContext(Dispatchers.IO) {
                    ApiClient(prefs.backendUrl).shareLink(
                        apiKey = apiKey,
                        rawText = text,
                        sharedAt = System.currentTimeMillis(),
                        fingerprint = fingerprint,
                    )
                }
                prefs.lastSavedClipboard = text
                getString(R.string.clipboard_saved)
            } catch (error: ApiClient.ApiException) {
                if (error.status == 422) {
                    getString(R.string.share_not_recognised)
                } else {
                    getString(R.string.clipboard_failed)
                }
            } catch (error: Exception) {
                getString(R.string.clipboard_failed)
            }
            finishWith(message)
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

    private fun finishWith(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
        finish()
        overridePendingTransition(0, 0)
    }
}

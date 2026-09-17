package edu.wellesley.scraper.ui

import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
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
 * From Android 10 only a focused app may read the clipboard, so an
 * activity has to come forward for an instant to do it. This one is
 * translucent, keeps no history and finishes immediately, so the system
 * returns to whatever was underneath -- which is the point: the link
 * gets recorded without leaving the app the operator is working in.
 *
 * It is reached from the floating button, so the sequence is: share,
 * copy link, tap. Nothing here touches the other app's interface; the
 * copying is a person's action, and this only picks up the result.
 */
class ClipboardReaderActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        overridePendingTransition(0, 0)

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

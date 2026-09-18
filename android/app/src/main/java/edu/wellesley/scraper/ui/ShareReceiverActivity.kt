package edu.wellesley.scraper.ui

import android.content.Intent
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
 * Receives a link the participant shares out of Douyin or TikTok.
 *
 * The accessibility tree never contains a video id, so this is the
 * only route to a real, citable URL. It stays a manual action: having
 * the service drive the share sheet itself would be invisible to the
 * participant and would break on every app update.
 *
 * Two taps and no clipboard: share, then pick this app out of the
 * system row of the platform's own share sheet. Shorter than copy
 * link plus the floating button, and nothing depends on the clipboard
 * being readable.
 *
 * A ComponentActivity, not an AppCompatActivity. AppCompat throws on
 * creation unless the theme descends from Theme.AppCompat, and the
 * manifest gives this one the translucent system theme -- so every
 * share into the app killed the process, taking the capture service
 * and its overlay with it. The same bug as ClipboardReaderActivity
 * had, in the file next to it, found only by reading this one.
 */
class ShareReceiverActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val text = intent
            ?.takeIf { it.action == Intent.ACTION_SEND }
            ?.getStringExtra(Intent.EXTRA_TEXT)
            ?.trim()

        if (text.isNullOrEmpty()) {
            finishWith(R.string.share_not_recognised)
            return
        }

        val prefs = Prefs(this)
        val apiKey = prefs.apiKey
        if (apiKey == null) {
            finishWith(R.string.share_not_registered)
            return
        }

        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    // The fingerprint of the post last read off the
                    // screen, so this link can be paired to it exactly
                    // rather than by nearest-in-time.
                    ApiClient(prefs.backendUrl).shareLink(
                        apiKey = apiKey,
                        rawText = text,
                        sharedAt = System.currentTimeMillis(),
                        fingerprint = CaptureStats.lastFingerprint,
                    )
                }
                finishWith(R.string.share_saved)
            } catch (error: ApiClient.ApiException) {
                finishWith(
                    if (error.status == 422) R.string.share_not_recognised
                    else R.string.share_not_registered
                )
            } catch (error: Exception) {
                finishWith(R.string.share_not_recognised)
            }
        }
    }

    private fun finishWith(messageRes: Int) {
        Toast.makeText(this, messageRes, Toast.LENGTH_SHORT).show()
        finish()
    }
}

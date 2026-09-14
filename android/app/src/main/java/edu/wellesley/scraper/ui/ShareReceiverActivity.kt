package edu.wellesley.scraper.ui

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import edu.wellesley.scraper.R
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.net.ApiClient
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
 */
class ShareReceiverActivity : AppCompatActivity() {

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
                    ApiClient(prefs.backendUrl)
                        .shareLink(apiKey, text, System.currentTimeMillis())
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

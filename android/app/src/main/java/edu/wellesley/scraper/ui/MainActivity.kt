package edu.wellesley.scraper.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import edu.wellesley.scraper.R
import edu.wellesley.scraper.data.CaptureDatabase
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.databinding.ActivityMainBinding
import edu.wellesley.scraper.net.ApiClient
import edu.wellesley.scraper.net.SyncWorker
import edu.wellesley.scraper.service.AutoCapture
import edu.wellesley.scraper.service.CaptureAccessibilityService
import edu.wellesley.scraper.service.CaptureStats
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Status panel. Deliberately plain: participants should not need to use it. */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.accessibilityButton.setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        binding.registerButton.setOnClickListener {
            startActivity(Intent(this, RegisterActivity::class.java))
        }
        binding.syncButton.setOnClickListener { SyncWorker.enqueue(this) }
        binding.pasteButton.setOnClickListener { saveTypedLink() }
        binding.selfCheckRefresh.setOnClickListener { showSelfCheck() }
        binding.selfCheckCopy.setOnClickListener { copySelfCheck() }
        binding.saveButtonToggle.setOnClickListener { toggleSaveButton() }
        binding.autoDryRun.setOnClickListener { startAssisted(AutoCapture.Mode.DRY_RUN) }
        binding.autoStart.setOnClickListener { startAssisted(AutoCapture.Mode.LIVE) }
        binding.autoStop.setOnClickListener {
            CaptureAccessibilityService.stopAssisted()
            toast(getString(R.string.auto_stopped))
            showSelfCheck()
            refreshRunState()
        }

        lifecycleScope.launch {
            CaptureDatabase.get(this@MainActivity).captureDao().pendingCount()
                .collectLatest { count ->
                    binding.pendingText.text = getString(R.string.status_pending, count)
                }
        }
    }

    private fun showSelfCheck() {
        binding.selfCheckText.text = CaptureStats.report()
    }

    /**
     * Record a link copied out of Douyin or TikTok, with no typing.
     *
     * Measured on a device: no video id appears anywhere in TikTok's
     * accessibility tree, in 58 frames. So an id can only come from a
     * link, and a link only from someone copying one. What is left to
     * decide is what recording it costs per video -- hence this, and
     * the floating button, which removes the app switch as well.
     *
     * The copying itself stays a person's action. This app does not
     * drive another app's interface; it observes the result of someone
     * choosing to share.
     */
    private fun captureCopiedLink() {
        val prefs = Prefs(this)
        val apiKey = prefs.apiKey ?: return

        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val text = clipboard.primaryClip
            ?.takeIf { it.itemCount > 0 }
            ?.getItemAt(0)
            ?.coerceToText(this)
            ?.toString()
            ?.trim()
            ?: return

        if (text.isEmpty() || text == prefs.lastSavedClipboard) return
        if (!LOOKS_LIKE_A_POST_LINK.containsMatchIn(text)) return

        val fingerprint = CaptureStats.lastFingerprint
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    ApiClient(prefs.backendUrl).shareLink(
                        apiKey = apiKey,
                        rawText = text,
                        sharedAt = System.currentTimeMillis(),
                        fingerprint = fingerprint,
                    )
                }
                prefs.lastSavedClipboard = text
                toast(getString(R.string.clipboard_saved))
                showSelfCheck()
            } catch (error: Exception) {
                // Nothing was typed, so say nothing on failure beyond
                // this: a silent retry happens next time the app opens.
                toast(getString(R.string.clipboard_failed))
            }
        }
    }

    /**
     * Start an assisted run in whichever app is in front.
     *
     * The run cannot start from here, because "in front" means the
     * feed and this app is in front right now. So it starts armed and
     * the first step waits a moment -- long enough to switch back to
     * Douyin or TikTok. The service refuses if the app in front then
     * is not one of them.
     *
     * A dry run first, always: the wording inside the share sheet has
     * never been read off a device, so the selectors are guesses until
     * one run reports what it found.
     */
    private fun startAssisted(mode: AutoCapture.Mode) {
        val refusal = CaptureAccessibilityService.armAssisted(mode, MINUTES, VIDEOS)
        if (refusal != null) {
            toast(refusal)
            return
        }
        toast(
            getString(
                if (mode == AutoCapture.Mode.DRY_RUN) R.string.auto_dry_started
                else R.string.auto_started
            )
        )
        refreshRunState()
    }

    /**
     * Put the run's state on screen, and let only the buttons that mean
     * something be pressed.
     *
     * A run ends on its own -- the time limit, the video limit, leaving
     * the app -- and nothing told this screen, so after one run it was
     * impossible to tell from here whether a second one had started.
     * Three always-enabled buttons and a self-check panel still naming
     * the previous run read as "stuck on stop".
     *
     * It refreshes on a tick as well as on each press, because the end
     * of a run arrives while this activity is in the background.
     */
    private fun refreshRunState() {
        val state = CaptureAccessibilityService.runState()
        binding.autoStatus.setText(
            when (state) {
                CaptureAccessibilityService.State.SERVICE_OFF -> R.string.auto_state_service_off
                CaptureAccessibilityService.State.IDLE -> R.string.auto_state_idle
                CaptureAccessibilityService.State.ARMED -> R.string.auto_state_armed
                CaptureAccessibilityService.State.RUNNING -> R.string.auto_state_running
            }
        )
        val idle = state == CaptureAccessibilityService.State.IDLE
        binding.autoDryRun.isEnabled = idle
        binding.autoStart.isEnabled = idle
        binding.autoStop.isEnabled = !idle &&
            state != CaptureAccessibilityService.State.SERVICE_OFF
    }

    /**
     * Turn the floating button on, asking for the overlay permission
     * first if it has not been granted.
     */
    private fun toggleSaveButton() {
        val prefs = Prefs(this)
        if (prefs.showSaveButton) {
            prefs.showSaveButton = false
            refreshSaveButtonLabel()
            return
        }

        if (!Settings.canDrawOverlays(this)) {
            toast(getString(R.string.save_button_needs_permission))
            startActivity(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName"),
                )
            )
            return
        }

        prefs.showSaveButton = true
        refreshSaveButtonLabel()
    }

    private fun refreshSaveButtonLabel() {
        binding.saveButtonToggle.setText(
            if (Prefs(this).showSaveButton) R.string.save_button_disable
            else R.string.save_button_enable
        )
    }

    private fun copySelfCheck() {
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("self-check", CaptureStats.report()))
        toast(getString(R.string.selfcheck_copied))
    }

    /**
     * Save a link the participant pasted in by hand.
     *
     * Douyin and TikTok do not always offer third-party apps in their
     * own share sheet, so "copy link, paste here" has to work as a
     * fallback or link capture depends on a menu we do not control.
     */
    private fun saveTypedLink() {
        val text = binding.pasteInput.text?.toString()?.trim().orEmpty()
        if (text.isEmpty()) {
            toast(getString(R.string.paste_empty))
            return
        }

        val prefs = Prefs(this)
        val apiKey = prefs.apiKey
        if (apiKey == null) {
            toast(getString(R.string.share_not_registered))
            return
        }

        binding.pasteButton.isEnabled = false
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    ApiClient(prefs.backendUrl).shareLink(
                        apiKey = apiKey,
                        rawText = text,
                        sharedAt = System.currentTimeMillis(),
                        fingerprint = CaptureStats.lastFingerprint,
                    )
                }
                binding.pasteInput.setText("")
                toast(getString(R.string.share_saved))
            } catch (error: ApiClient.ApiException) {
                toast(
                    getString(
                        if (error.status == 422) R.string.share_not_recognised
                        else R.string.share_not_registered
                    )
                )
            } catch (error: Exception) {
                toast(getString(R.string.share_not_recognised))
            } finally {
                binding.pasteButton.isEnabled = true
            }
        }
    }

    private fun toast(message: String) =
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()

    override fun onResume() {
        super.onResume()
        ticker.removeCallbacks(stateTicker)
        stateTicker.run()
        val prefs = Prefs(this)
        binding.statusText.text = if (prefs.isRegistered) {
            getString(R.string.status_registered, prefs.participantId.orEmpty())
        } else {
            getString(R.string.status_not_registered)
        }
        refreshSaveButtonLabel()
        showSelfCheck()
    }

    override fun onPause() {
        super.onPause()
        ticker.removeCallbacks(stateTicker)
    }

    private val ticker = Handler(Looper.getMainLooper())

    private val stateTicker = object : Runnable {
        override fun run() {
            refreshRunState()
            ticker.postDelayed(this, STATE_TICK_MILLIS)
        }
    }

    /**
     * The clipboard is readable only once this window holds focus, so
     * the read waits for it. onResume is too early and came back empty.
     */
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) captureCopiedLink()
    }

    private companion object {
        /** How long a run may last, and how many videos it may step through. */
        const val MINUTES = 30
        const val VIDEOS = 300

        /** Only redraws four views; a second is unnoticeable and enough. */
        const val STATE_TICK_MILLIS = 1_000L

        /** Cheap pre-filter; the server does the real extraction. */
        val LOOKS_LIKE_A_POST_LINK = Regex(
            """(?:v\.douyin\.com|douyin\.com/video|tiktok\.com|vm\.tiktok|vt\.tiktok)""",
            RegexOption.IGNORE_CASE,
        )
    }
}

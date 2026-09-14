package edu.wellesley.scraper.ui

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import edu.wellesley.scraper.R
import edu.wellesley.scraper.data.CaptureDatabase
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.databinding.ActivityMainBinding
import edu.wellesley.scraper.net.SyncWorker
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

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

        lifecycleScope.launch {
            CaptureDatabase.get(this@MainActivity).captureDao().pendingCount()
                .collectLatest { count ->
                    binding.pendingText.text = getString(R.string.status_pending, count)
                }
        }
    }

    override fun onResume() {
        super.onResume()
        val prefs = Prefs(this)
        binding.statusText.text = if (prefs.isRegistered) {
            getString(R.string.status_registered, prefs.participantId.orEmpty())
        } else {
            getString(R.string.status_not_registered)
        }
    }
}

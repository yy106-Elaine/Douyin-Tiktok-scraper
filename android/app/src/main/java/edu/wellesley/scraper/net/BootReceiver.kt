package edu.wellesley.scraper.net

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Flush anything that was still pending when the phone was switched off. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            SyncWorker.enqueue(context)
        }
    }
}

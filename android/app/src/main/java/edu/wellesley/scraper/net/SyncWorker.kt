package edu.wellesley.scraper.net

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import edu.wellesley.scraper.data.CaptureDatabase
import edu.wellesley.scraper.data.LinkQueue
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.service.CaptureStats
import java.util.concurrent.TimeUnit

/**
 * Uploads pending captures.
 *
 * WorkManager rather than a foreground service: uploads are not
 * time-critical, and letting the system batch them keeps the app off
 * the battery-usage screen, which matters when a participant has the
 * phone for weeks.
 */
class SyncWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        val apiKey = prefs.apiKey ?: return Result.success()

        // Links first. They are the only record of which video was on
        // screen -- a capture can be read off the feed again tomorrow,
        // a link cannot be re-copied once the clipboard has moved on.
        val links = LinkQueue.drain(applicationContext)
        CaptureStats.onLinkDrain(links)
        val linksLeft = LinkQueue.waiting(applicationContext) > 0

        sendAuthorIdentities(prefs, apiKey)

        val dao = CaptureDatabase.get(applicationContext).captureDao()
        val batch = dao.pendingBatch(BATCH_SIZE)
        if (batch.isEmpty()) return if (linksLeft) Result.retry() else Result.success()

        return try {
            ApiClient(prefs.backendUrl).uploadBatch(apiKey, prefs.deviceId, batch)
            dao.markSynced(batch.map { it.id })
            dao.purgeSyncedBefore(System.currentTimeMillis() - RETENTION_MILLIS)
            // More may be waiting; come straight back for the next batch.
            if (batch.size == BATCH_SIZE) enqueue(applicationContext)
            if (linksLeft) Result.retry() else Result.success()
        } catch (error: ApiClient.ApiException) {
            // A rejected key will never succeed on retry; anything else might.
            if (error.status == 401) Result.failure() else Result.retry()
        } catch (error: Exception) {
            Result.retry()
        }
    }

    /**
     * Hand over any 抖音号 read since the last upload, and forget them
     * only once the server has them.
     *
     * Kept in preferences rather than the database because there are
     * a handful per session and they are already deduplicated by the
     * visited-authors set; a table would be more machinery than the
     * problem has.
     */
    private fun sendAuthorIdentities(prefs: Prefs, apiKey: String) {
        val pending = prefs.pendingAuthorIds
        if (pending.isEmpty()) return
        val identities = pending.mapNotNull { entry ->
            val parts = entry.split('\u0000')
            if (parts.size == 2 && parts[0].isNotBlank() && parts[1].isNotBlank()) {
                parts[0] to parts[1]
            } else {
                null
            }
        }
        try {
            ApiClient(prefs.backendUrl).authorIdentities(apiKey, identities)
            prefs.pendingAuthorIds = emptySet()
        } catch (error: Exception) {
            // Left queued; the next run tries again.
            CaptureStats.onAutoStep("author ids not sent: ${error.javaClass.simpleName}")
        }
    }

    companion object {
        private const val BATCH_SIZE = 200
        private const val WORK_NAME = "capture-sync"
        private val RETENTION_MILLIS = TimeUnit.DAYS.toMillis(7)

        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
        }
    }
}

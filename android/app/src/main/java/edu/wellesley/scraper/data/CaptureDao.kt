package edu.wellesley.scraper.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface CaptureDao {

    @Insert
    suspend fun insert(capture: CaptureEntity)

    @Query("SELECT * FROM captures WHERE synced = 0 ORDER BY capturedAt LIMIT :limit")
    suspend fun pendingBatch(limit: Int): List<CaptureEntity>

    @Query("UPDATE captures SET synced = 1 WHERE id IN (:ids)")
    suspend fun markSynced(ids: List<Long>)

    @Query("SELECT COUNT(*) FROM captures WHERE synced = 0")
    fun pendingCount(): Flow<Int>

    /**
     * Same post, same local day -- the on-device guard against
     * re-uploading a post the participant scrolls past repeatedly. The
     * server enforces this again; this copy just saves bandwidth.
     */
    @Query(
        "SELECT COUNT(*) FROM captures WHERE fingerprint = :fingerprint " +
            "AND capturedAt >= :dayStart"
    )
    suspend fun countSince(fingerprint: String, dayStart: Long): Int

    @Query("DELETE FROM captures WHERE synced = 1 AND capturedAt < :before")
    suspend fun purgeSyncedBefore(before: Long)
}

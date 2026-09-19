package edu.wellesley.scraper.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface LinkDao {

    @Insert
    suspend fun insert(link: LinkEntity): Long

    @Query("SELECT * FROM links ORDER BY sharedAt LIMIT :limit")
    suspend fun pending(limit: Int): List<LinkEntity>

    @Query("DELETE FROM links WHERE id = :id")
    suspend fun delete(id: Long)

    @Query("UPDATE links SET attempts = attempts + 1 WHERE id = :id")
    suspend fun countFailure(id: Long)

    @Query("SELECT COUNT(*) FROM links")
    fun pendingCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM links")
    suspend fun pendingNow(): Int

    /**
     * The same clipboard text twice is the same copy seen twice, not
     * two posts: Douyin leaves the text in place, so a run that fails
     * to copy would otherwise queue the previous video's link again.
     */
    @Query("SELECT COUNT(*) FROM links WHERE rawText = :rawText")
    suspend fun countQueued(rawText: String): Int

    /**
     * The row queued most recently, which is the video the run is on.
     *
     * The link is queued when it is copied and the profile is opened
     * after that, so the id arrives a step later than the row it
     * belongs to.
     */
    @Query("SELECT * FROM links ORDER BY id DESC LIMIT 1")
    suspend fun newest(): LinkEntity?

    @Query("UPDATE links SET authorHandle = :handle WHERE id = :id")
    suspend fun setAuthorHandle(id: Long, handle: String)
}

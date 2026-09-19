package edu.wellesley.scraper.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * A copied link, written to disk before any attempt to upload it.
 *
 * Links used to be posted straight from the clipboard reader and
 * dropped on the floor if the post failed. That is survivable when
 * someone is copying links by hand and can see the toast; it is not
 * survivable during an assisted run, where thirty minutes of
 * collection can disappear because the backend was asleep and nobody
 * was watching the screen. The row is deleted once the server has it.
 */
@Entity(tableName = "links", indices = [Index("sharedAt")])
data class LinkEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    /** The clipboard text verbatim; the server does the extraction. */
    val rawText: String,
    val sharedAt: Long,
    /** The post last read off the screen, so the server can pair it. */
    val fingerprint: String?,
    /** How many uploads have failed, for the self-check to show. */
    val attempts: Int = 0,
)

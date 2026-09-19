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
    /**
     * The 抖音号, when the run opened this video's author's profile.
     *
     * On the link rather than keyed by display name. The link
     * identifies the video and the video identifies its author, so no
     * name has to be matched for the association to hold -- and the
     * first attempt at name matching filed an id under a neighbour's
     * nickname, which is a false identification nothing downstream can
     * detect.
     */
    val authorHandle: String? = null,

    /** How many uploads have failed, for the self-check to show. */
    val attempts: Int = 0,
)

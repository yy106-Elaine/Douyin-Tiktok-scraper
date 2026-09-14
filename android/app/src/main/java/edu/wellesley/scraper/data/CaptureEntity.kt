package edu.wellesley.scraper.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "captures",
    indices = [Index("synced"), Index("fingerprint")],
)
data class CaptureEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val platformPackage: String,
    val fingerprint: String,
    val capturedAt: Long,
    /** JSON object of the parsed fields, uploaded verbatim. */
    val payloadJson: String,
    val synced: Boolean = false,
)

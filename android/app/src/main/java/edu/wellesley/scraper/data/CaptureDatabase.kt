package edu.wellesley.scraper.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [CaptureEntity::class, LinkEntity::class],
    version = 2,
    exportSchema = false,
)
abstract class CaptureDatabase : RoomDatabase() {

    abstract fun captureDao(): CaptureDao

    abstract fun linkDao(): LinkDao

    companion object {
        @Volatile
        private var instance: CaptureDatabase? = null

        /**
         * Adds the link queue. A migration rather than a destructive
         * fallback: the captures table on a study phone holds work that
         * has not reached the server yet, and dropping it to add a
         * table would throw that away.
         */
        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS `links` (" +
                        "`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                        "`rawText` TEXT NOT NULL, " +
                        "`sharedAt` INTEGER NOT NULL, " +
                        "`fingerprint` TEXT, " +
                        "`attempts` INTEGER NOT NULL DEFAULT 0)"
                )
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_links_sharedAt` ON `links` (`sharedAt`)")
            }
        }

        fun get(context: Context): CaptureDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    CaptureDatabase::class.java,
                    "captures.db",
                ).addMigrations(MIGRATION_1_2).build().also { instance = it }
            }
    }
}

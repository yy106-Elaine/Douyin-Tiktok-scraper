package edu.wellesley.scraper.net

import edu.wellesley.scraper.data.CaptureEntity
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** Thin HTTP client. No third-party networking dependency on purpose. */
class ApiClient(private val baseUrl: String) {

    class ApiException(val status: Int, message: String) : Exception(message)

    data class Registration(val participantId: String, val apiKey: String)

    fun register(email: String, deviceId: String): Registration {
        val body = JSONObject()
            .put("email", email)
            .put("device_id", deviceId)
        val response = post("/api/auth/register", body.toString(), apiKey = null)
        return Registration(
            participantId = response.getString("participant_id"),
            apiKey = response.getString("api_key"),
        )
    }

    fun uploadBatch(apiKey: String, deviceId: String, captures: List<CaptureEntity>): Int {
        val array = JSONArray()
        for (capture in captures) {
            array.put(
                JSONObject()
                    .put("platform_package", capture.platformPackage)
                    .put("fingerprint", capture.fingerprint)
                    .put("captured_at", isoUtc(capture.capturedAt))
                    .put("payload", JSONObject(capture.payloadJson))
            )
        }
        val body = JSONObject().put("device_id", deviceId).put("captures", array)
        val response = post("/api/captures/batch", body.toString(), apiKey)
        return response.optInt("accepted", 0)
    }

    /**
     * Submit a link. [fingerprint] names the post it belongs to, when
     * known, so the server pairs it exactly rather than by time window.
     */
    fun shareLink(
        apiKey: String,
        rawText: String,
        sharedAt: Long,
        fingerprint: String? = null,
    ): JSONObject {
        val body = JSONObject()
            .put("raw_text", rawText)
            .put("shared_at", isoUtc(sharedAt))
        fingerprint?.let { body.put("fingerprint", it) }
        return post("/api/links/shared", body.toString(), apiKey)
    }

    private fun post(path: String, json: String, apiKey: String?): JSONObject {
        val connection = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection)
        return try {
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.connectTimeout = 15_000
            connection.readTimeout = 30_000
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            apiKey?.let { connection.setRequestProperty("X-API-Key", it) }
            connection.outputStream.use { it.write(json.toByteArray(Charsets.UTF_8)) }

            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use(BufferedReader::readText).orEmpty()
            if (status !in 200..299) throw ApiException(status, text.take(500))
            if (text.isBlank()) JSONObject() else JSONObject(text)
        } finally {
            connection.disconnect()
        }
    }

    private companion object {
        fun isoUtc(millis: Long): String {
            val format = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
            format.timeZone = TimeZone.getTimeZone("UTC")
            return format.format(Date(millis))
        }
    }
}

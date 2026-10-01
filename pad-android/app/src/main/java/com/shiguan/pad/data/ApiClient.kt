package com.shiguan.pad.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * PC 端数据服务客户端（`tools/pad_server.py`）。
 *
 * 只用 `HttpURLConnection`，不引第三方网络库 —— 少一个依赖就少一份下载与踩坑。
 * 所有调用都在 IO 线程上（`withContext(Dispatchers.IO)`）。
 */
object ApiClient {

    /** 服务器基址，例如 `http://192.168.3.41:8801`。 */
    @Volatile
    var baseUrl: String = "http://192.168.3.41:8801"

    private fun url(path: String) = URL(baseUrl.trimEnd('/') + path)

    private fun get(path: String, timeoutMs: Int): String {
        val c = url(path).openConnection() as HttpURLConnection
        return try {
            c.requestMethod = "GET"
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            c.setRequestProperty("Accept", "application/json")
            val code = c.responseCode
            val body = (if (code in 200..299) c.inputStream else c.errorStream)
                ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (code !in 200..299) throw IllegalStateException("HTTP $code：$body")
            body
        } finally {
            c.disconnect()
        }
    }

    /** 探活：平板用它判断「PC 那边服务起没起」。 */
    suspend fun health(timeoutMs: Int = 3000): Boolean = withContext(Dispatchers.IO) {
        try {
            get("/api/health", timeoutMs).contains("\"ok\"")
        } catch (_: Exception) {
            false
        }
    }

    /** 取全量数据。首次取数服务端要起 Tk，给足超时。 */
    suspend fun fetchData(timeoutMs: Int = 60_000): PersonData =
        withContext(Dispatchers.IO) {
            PersonData.parse(JSONObject(get("/api/data", timeoutMs)))
        }

    /** 强制服务端重取（换档 / 改数据后用）。 */
    suspend fun reload(timeoutMs: Int = 60_000): PersonData =
        withContext(Dispatchers.IO) {
            PersonData.parse(JSONObject(get("/api/reload", timeoutMs)))
        }
}

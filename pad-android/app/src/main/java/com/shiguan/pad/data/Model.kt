package com.shiguan.pad.data

import org.json.JSONArray
import org.json.JSONObject

/**
 * 服务端 `/api/data` 的载荷（见 `tools/pad_data.py`）。
 *
 * 字段名与服务端一一对应，**不要在这里重新解释口径** ——
 * 计数、列宽、列名全部由服务端从 Tkinter 同源取好，客户端只负责显示。
 */
data class PersonData(
    val book: String,
    val slot: String,
    val total: Int,
    val heads: List<String>,
    val rows: List<List<String>>,
    val colw: List<Int>,
    val center: Set<String>,
    val stats: List<Pair<String, Int>>,
    val stats2: List<Pair<String, Int>>,
    val tiers: List<String>,
    val tabs: List<Pair<String, Int>>,
    val bookCount: Int,     // 已入谱
    val watchCount: Int,    // 续谱名单
    val record: Int,        // 实录层人数（状态栏「实录」）
    val ts: String,
) {
    val headIndex: Map<String, Int> = heads.withIndex().associate { (i, h) -> h to i }
    fun col(row: List<String>, h: String): String {
        val i = headIndex[h] ?: return "—"
        return row.getOrNull(i).takeUnless { it.isNullOrEmpty() } ?: "—"
    }

    companion object {
        private fun pairs(a: JSONArray?): List<Pair<String, Int>> {
            if (a == null) return emptyList()
            return (0 until a.length()).map { i ->
                val o = a.getJSONArray(i)
                o.getString(0) to o.optInt(1, 0)
            }
        }

        fun parse(o: JSONObject): PersonData {
            val heads: List<String> = o.getJSONArray("heads").let { a ->
                (0 until a.length()).map { a.getString(it) }
            }
            val rows: List<List<String>> = o.getJSONArray("rows").let { a ->
                (0 until a.length()).map { i ->
                    val r = a.getJSONArray(i)
                    (0 until r.length()).map { j -> r.optString(j, "") }
                }
            }
            val colw: List<Int> = o.optJSONArray("colw")?.let { a ->
                (0 until a.length()).map { a.optInt(it, 80) }
            } ?: heads.map { 80 }
            val center: Set<String> = o.optJSONArray("center")?.let { a ->
                (0 until a.length()).map { a.getString(it) }.toSet()
            } ?: emptySet()
            val gen = o.optJSONObject("gen")
            return PersonData(
                book = o.optString("book", "—"),
                slot = o.optString("slot", "—"),
                total = o.optInt("total", 0),
                heads = heads,
                rows = rows,
                colw = colw,
                center = center,
                stats = pairs(o.optJSONArray("stats")),
                stats2 = pairs(o.optJSONArray("stats2")),
                tiers = o.optJSONArray("tiers")?.let { a ->
                    (0 until a.length()).map { a.getString(it) }
                } ?: emptyList(),
                tabs = pairs(o.optJSONArray("tabs")),
                bookCount = gen?.optInt("book", 0) ?: 0,
                watchCount = gen?.optInt("watch", 0) ?: 0,
                record = o.optInt("record", 0),
                ts = o.optString("ts", "—"),
            )
        }
    }
}

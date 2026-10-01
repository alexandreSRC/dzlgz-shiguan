package com.shiguan.pad.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.shiguan.pad.data.PersonData

/** 卡片外壳（`.card` + `h4` 标题条）。 */
@Composable
fun Card(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 6.dp)
            .clip(RoundedCornerShape(S.r6))
            .background(C.bgCard)
            .border(1.dp, C.border2, RoundedCornerShape(S.r6)),
    ) {
        if (title.isNotEmpty()) {
            Column(Modifier.fillMaxWidth()) {
                Box(Modifier.padding(horizontal = 8.dp, vertical = 5.dp)) {
                    T(title, color = C.text3, size = S.fs115, bold = true)
                }
                // 标题条下的分隔线（`h4` 的 border-bottom）—— 用 1dp 色块画，
                // 因为 Compose 的 `border(0.dp)` 什么都不画。
                Box(Modifier.fillMaxWidth().height(1.dp).background(C.border2))
            }
        }
        content()
    }
}

/** 左栏（265dp）：人物 / 筛选 / 搜索 / 续谱名单。 */
@Composable
fun SidePanel(d: PersonData, onPicked: (Int) -> Unit) {
    Column(
        modifier = Modifier
            .width(S.side)
            .fillMaxHeight()
            .background(C.bgPanel)
            .padding(S.pad)
            .verticalScroll(rememberScrollState()),
    ) {
        // ── 人物：谱牒总谱 / 全部人物（选中 = 全部人物，与 Tk 截图一致）──
        Card("人物") {
            d.tabs.forEachIndexed { i, (name, n) ->
                val on = i == 1
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(if (on) C.accentSoft else C.bgCard)
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    T(name, color = if (on) C.accent else C.text2, size = S.fs125, bold = on)
                    T("$n", color = if (on) C.accent else C.text3, size = S.fs11)
                }
            }
        }

        // ── 筛选：8 项计数（圆角胶囊）──
        Card("筛选") {
            val items = d.stats + d.stats2
            Column(Modifier.padding(horizontal = 8.dp, vertical = 6.dp)) {
                items.chunked(2).forEach { row ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 1.5.dp),
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        row.forEach { (k, v) ->
                            Row(
                                modifier = Modifier
                                    .weight(1f)
                                    .clip(RoundedCornerShape(S.r))
                                    .background(C.bgCard)
                                    .border(1.dp, C.border2, RoundedCornerShape(S.r))
                                    .padding(horizontal = 6.dp, vertical = 2.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                T(k, color = C.text2, size = S.fs115)
                                T("$v", color = C.text, size = S.fs115)
                            }
                        }
                        if (row.size == 1) Spacer(Modifier.weight(1f))
                    }
                }
            }
            // 已入谱 / 续谱名单
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 3.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                T("已入谱", color = C.text2, size = S.fs115)
                T("${d.bookCount}", color = C.text, size = S.fs115, bold = true)
            }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 3.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                T("续谱名单", color = C.text2, size = S.fs115)
                T("${d.watchCount}", color = C.text, size = S.fs115, bold = true)
            }
        }

        // ── 男女等级：6 格（含「丁」）──
        Card("男女等级") {
            Column(Modifier.padding(horizontal = 8.dp, vertical = 2.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                    d.tiers.forEach { t ->
                        val on = t == "上"
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .height(22.dp)
                                .clip(RoundedCornerShape(S.r))
                                .background(if (on) C.accent else C.bgCard)
                                .border(1.dp, if (on) C.accent else C.border,
                                    RoundedCornerShape(S.r)),
                            contentAlignment = Alignment.Center,
                        ) {
                            T(t, color = if (on) C.accentOn else C.text2,
                                size = S.fs12, bold = on)
                        }
                    }
                }
            }
        }

        // ── 命中 / 清空 / 全选 ──
        Card("") {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                T("命中", color = C.text2, size = S.fs115)
                Spacer(Modifier.width(6.dp))
                T("${d.total} / ${d.total} 人", color = C.text, size = S.fs115, bold = true)
                Spacer(Modifier.weight(1f))
                Mini("清空")
                Spacer(Modifier.width(6.dp))
                Mini("全选")
            }
        }

        // ── 搜索 ──
        Card("搜索") {
            Box(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 6.dp)
                    .height(24.dp)
                    .clip(RoundedCornerShape(S.r))
                    .background(C.bgInput)
                    .border(1.dp, C.border, RoundedCornerShape(S.r))
                    .padding(horizontal = 7.dp),
                contentAlignment = Alignment.CenterStart,
            ) { T("姓名 / 尊号 / 封国…", color = C.text3, size = S.fs12) }
        }

        // ── 续谱名单 ──
        Card("★ 续谱名单：${d.watchCount} 人") {}
    }
}

/** 小按钮（`.mini`）。 */
@Composable
fun Mini(label: String) {
    Box(
        modifier = Modifier
            .height(22.dp)
            .clip(RoundedCornerShape(S.r))
            .background(C.bgCard)
            .border(1.dp, C.border, RoundedCornerShape(S.r))
            .padding(horizontal = 8.dp),
        contentAlignment = Alignment.Center,
    ) { T(label, color = C.text2, size = S.fs115) }
}

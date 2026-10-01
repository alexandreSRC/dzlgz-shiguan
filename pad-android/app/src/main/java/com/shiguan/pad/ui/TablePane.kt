package com.shiguan.pad.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.shiguan.pad.data.PersonData

/**
 * 中栏：标题行 + 表格。
 *
 * ★ 列宽用**服务端给的 Tk 实测值**（1205 > 中栏 515）⇒ 和 Tk 一样横向滚动、内容被裁。
 *   这看着"不如自适应好看"，但**复刻的验收标准是像被复刻方**，不是我觉得更好看。
 */
@Composable
fun TablePane(
    d: PersonData,
    selected: Int,
    onSelect: (Int) -> Unit,
) {
    val h = rememberScrollState()
    val nIdx = d.headIndex

    Column(Modifier.fillMaxSize().background(C.bgPanel)) {
        // ── 标题行 ──
        Row(
            Modifier.fillMaxWidth().padding(start = 10.dp, end = 10.dp, top = 6.dp, bottom = 3.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            T("人物 · 合并总表", color = C.text, size = S.fs125, bold = true)
            Spacer(Modifier.width(8.dp))
            T("· ${d.total} 条", color = C.text2, size = S.fs125, bold = true)
            Spacer(Modifier.width(8.dp))
            val who = if (selected in d.rows.indices) d.col(d.rows[selected], "姓名") else "—"
            T(if (who == "—") "" else who, color = C.text, size = S.fs13, bold = true)
            Spacer(Modifier.width(6.dp))
            Badge("● 史实人物", hist = true)
            Spacer(Modifier.width(6.dp))
            Badge("谱")
            Spacer(Modifier.weight(1f))
            Locate()
        }

        // ── 表头（与数据行共用同一个水平滚动状态 ⇒ 横向自动对齐）──
        Box(
            Modifier.fillMaxWidth().padding(start = 6.dp, end = 6.dp),
        ) {
            Column(
                Modifier
                    .clip(RoundedCornerShape(topStart = S.r6, topEnd = S.r6))
                    .background(C.bgBar)
                    .border(1.dp, C.border2, RoundedCornerShape(topStart = S.r6, topEnd = S.r6)),
            ) {
                Row(Modifier.horizontalScroll(h)) {
                    d.heads.forEachIndexed { i, hName ->
                        CellBox(w = d.colw.getOrElse(i) { 80 }, head = true) {
                            T(
                                hName,
                                color = C.text3,
                                size = S.fs115,
                                bold = true,
                            )
                        }
                    }
                }
            }
        }

        // ── 数据行 ──
        Box(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(start = 6.dp, end = 6.dp, bottom = 6.dp),
        ) {
            LazyColumn(Modifier.fillMaxSize()) {
                itemsIndexed(d.rows) { idx, row ->
                    val dead = row.getOrNull(nIdx["卒年"] ?: -1).orEmpty().isNotEmpty()
                    val on = idx == selected
                    val bg = when {
                        on -> C.accentSoft
                        dead -> C.deadBg
                        else -> C.bgCard
                    }
                    val fg = when {
                        dead -> C.dead
                        else -> C.text
                    }
                    Column(Modifier.fillMaxWidth().background(bg)) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .height(S.rowH)
                                .horizontalScroll(h)
                                .clickableNoRipple { onSelect(idx) },
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            // 选中行左侧 3dp 绿条（原型是 box-shadow inset）
                            Box(
                                Modifier
                                    .width(3.dp)
                                    .fillMaxHeight()
                                    .background(if (on) C.accent else Color.Transparent),
                            )
                            d.heads.forEachIndexed { i, hName ->
                                val v = row.getOrElse(i) { "" }
                                val isNum = hName in d.center
                                val female = hName == "姓名" &&
                                    row.getOrNull(nIdx["性别"] ?: -1) == "女"
                                CellBox(w = d.colw.getOrElse(i) { 80 } - 3) {
                                    Text(
                                        text = v,
                                        color = if (female) C.spouse else fg,
                                        fontSize = S.fs115,
                                        fontFamily = if (isNum) FontFamily.SansSerif else null,
                                        fontWeight = if (female) FontWeight.Bold
                                        else FontWeight.Normal,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        textAlign = if (isNum) TextAlign.End else TextAlign.Start,
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                }
                            }
                        }
                        Box(Modifier.fillMaxWidth().height(1.dp).background(C.border2))
                    }
                }
            }
        }
    }
}

/** 一个单元格：定宽 + 左右 6dp 内距（取自原型 `td{padding:1px 6px}`）。 */
@Composable
private fun CellBox(
    w: Int,
    head: Boolean = false,
    content: @Composable () -> Unit,
) {
    Box(
        Modifier
            .width(w.dp)
            .padding(horizontal = 6.dp, vertical = if (head) 4.dp else 1.dp),
    ) { content() }
}

/** 标题行右端的「定位到表格」（`.locate`）。 */
@Composable
private fun Locate() {
    Box(
        Modifier
            .height(22.dp)
            .clip(RoundedCornerShape(S.r))
            .background(C.bgCard)
            .border(1.dp, C.border2, RoundedCornerShape(S.r))
            .padding(horizontal = 8.dp),
        contentAlignment = Alignment.Center,
    ) { T("定位到表格", color = C.text2, size = S.fs115, bold = true) }
}

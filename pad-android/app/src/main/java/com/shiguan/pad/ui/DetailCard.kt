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
import androidx.compose.ui.unit.dp
import com.shiguan.pad.data.PersonData

/** 详情卡左栏字段（`基本档案`）—— 顺序照 Tk 的 `PROFILE_ORDER`。 */
private val LAB_L = listOf(
    "姓名", "身份", "性别", "智略", "年龄", "等级", "谥号", "生年",
    "卒年", "天寿", "余寿", "文化", "性格", "势力", "世代",
)

/** 详情卡右栏字段（`亲属关系`）。 */
private val LAB_R = listOf(
    "父系", "母系", "配偶", "子女", "兄弟", "姐妹", "父系上溯", "后代下推",
)

/**
 * 右栏：详情卡（470dp，**6 列网格**）。
 *
 * 照原型的 `.grid6`：按钮各跨 2 列、政策/能力/特质整行跨全宽、
 * 左右栏共用行号（左 1+2 列、右 1+3 列），所以两栏的标签左沿天然成一条竖线。
 */
@Composable
fun DetailCard(sel: List<String>?, d: PersonData) {
    Column(
        Modifier
            .width(S.right)
            .fillMaxHeight()
            .background(C.bgPanel),
    ) {
        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(start = 8.dp, end = 8.dp, bottom = 8.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            // ── 三颗按钮：各跨 2 列（等宽）──
            Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
                ActBtn("立即入谱", Modifier.weight(1f), primary = true)
                Spacer(Modifier.width(5.dp))
                ActBtn("预约入谱", Modifier.weight(1f))
                Spacer(Modifier.width(5.dp))
                ActBtn("选定人物", Modifier.weight(1f))
            }

            // ── 三行整宽字段（政策 / 能力 / 特质）──
            FullRow("政策", listOf("—"))
            FullRow("能力", listOf("—"))
            FullRow("特质", listOf("—"))

            // ── 两栏段头（各跨 3 列）──
            Row(Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 1.dp)) {
                Cap("基本档案", Modifier.weight(1f))
                Cap("亲属关系", Modifier.weight(1f))
            }

            // ── 左右字段对：左 1+2 列、右 1+3 列 = 6 列 ──
            val n = maxOf(LAB_L.size, LAB_R.size)
            var k = 0
            while (k < n) {
                Row(Modifier.fillMaxWidth().padding(vertical = 1.dp)) {
                    LabVal(LAB_L.getOrNull(k), valOf(d, sel, LAB_L.getOrNull(k)),
                        1f, 2f)
                    LabVal(LAB_R.getOrNull(k), "—", 1f, 3f)
                }
                k++
            }
        }
    }
}

/** 取某字段的值：表格列里有就显示（空 → 「—」），没有的（世代等）先给「—」。 */
private fun valOf(d: PersonData, sel: List<String>?, h: String?): String {
    if (h == null || sel == null) return "—"
    return d.col(sel, h)
}

/** 详情卡里的按钮（`.act`，跨 2 列、文字左对齐）。 */
@Composable
private fun ActBtn(
    label: String,
    modifier: Modifier = Modifier,
    primary: Boolean = false,
) {
    Box(
        modifier = modifier
            .height(S.actH)
            .clip(RoundedCornerShape(S.r))
            .background(if (primary) C.accent else C.bgCard)
            .border(1.dp, if (primary) C.accent else C.border2, RoundedCornerShape(S.r))
            .padding(horizontal = 7.dp),
        // ★ 文字**左对齐**（原型 `anchor="w"`）：一串上下相邻的按钮共用
        //   一条汉字左沿，而不是各自居中、各偏各的。
        contentAlignment = Alignment.CenterStart,
    ) {
        T(label, color = if (primary) C.accentOn else C.text2, size = S.fs12, bold = true)
    }
}

/** 整行跨全宽的字段 + 标签链（`.fullrow` + `.chips`）。 */
@Composable
private fun FullRow(label: String, chips: List<String>) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 1.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(Modifier.width(46.dp)) { T(label, color = C.text3, size = S.fs115) }
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            chips.forEach { c ->
                Box(
                    Modifier
                        .clip(RoundedCornerShape(S.r8))
                        .background(C.bgCard)
                        .border(1.dp, C.border2, RoundedCornerShape(S.r8))
                        .padding(horizontal = 7.dp, vertical = 1.dp),
                ) { T(c, color = C.text2, size = S.fs115) }
            }
        }
    }
}

/** 段头（`.cap`，跨 3 列）。 */
@Composable
private fun Cap(label: String, modifier: Modifier = Modifier) {
    Box(modifier) { T(label, color = C.text3, size = S.fs115, bold = true) }
}

/**
 * 「标签 + 值」一对（`.lab1/.val1` 或 `.lab2/.val2`）。
 *
 * 必须是 `RowScope` 扩展 —— `Modifier.weight()` 只在行作用域里存在，
 * 写成普通函数会报 "Expression 'weight' of type Float cannot be invoked"。
 */
@Composable
private fun RowScope.LabVal(
    label: String?,
    value: String,
    labW: Float,
    valW: Float,
) {
    Row(
        Modifier.weight(labW + valW),
        verticalAlignment = Alignment.Top,
    ) {
        Box(Modifier.weight(labW)) {
            T(label ?: "", color = C.text3, size = S.fs115)
        }
        Box(Modifier.weight(valW)) {
            T(value, color = C.text, size = S.fs115)
        }
    }
}

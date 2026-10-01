package com.shiguan.pad.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 通用：一行文字（可指定颜色/字号/字重）。 */
@Composable
fun T(
    s: String,
    color: Color = C.text,
    size: androidx.compose.ui.unit.TextUnit = S.fs115,
    bold: Boolean = false,
) = Text(
    text = s,
    color = color,
    fontSize = size,
    fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal,
    maxLines = 1,
)

/** 顶栏页签：**大块矩形**（无圆角、与顶栏同高、选中整块青绿底）—— 照 Tk，不是圆角小块。 */
@Composable
fun Tab(label: String, on: Boolean, onClick: () -> Unit = {}) {
    Box(
        modifier = Modifier
            .fillMaxHeight()
            .background(if (on) C.accent else Color.Transparent)
            .clickableNoRipple(onClick)
            .padding(horizontal = S.tabPadH),
        contentAlignment = Alignment.Center,
    ) {
        T(
            label,
            color = if (on) C.accentOn else C.text2,
            size = S.fs125,
            bold = true,
        )
    }
}

/** 顶栏右侧的圆角胶囊（存档 xxx / ⟲ 续谱 / ⚙）。 */
@Composable
fun Pill(label: String, value: String? = null, rec: Boolean = false) {
    Row(
        modifier = Modifier
            .height(S.pillH)
            .clip(RoundedCornerShape(S.pillH / 2))
            .background(C.bgCard)
            .border(1.dp, if (rec) C.accent else C.border, RoundedCornerShape(S.pillH / 2))
            .padding(horizontal = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        Box {
            Row(verticalAlignment = Alignment.CenterVertically) {
                T(label, color = if (rec) C.accent else C.text2, size = S.fs115)
                if (value != null) {
                    Spacer(Modifier.width(5.dp))
                    T(value, color = C.text, size = S.fs115, bold = true)
                }
            }
        }
    }
}

/** 工具栏按钮的三种语义色（与主题语义一一对应）。 */
enum class TbKind { Normal, Edit, Danger }

/** 工具栏按钮（`.tb`）。 */
@Composable
fun ToolBtn(
    label: String,
    kind: TbKind = TbKind.Normal,
    onClick: () -> Unit = {},
) {
    val bg = when (kind) {
        TbKind.Edit -> C.editSoft
        TbKind.Danger -> C.dangerSoft
        TbKind.Normal -> Color.Transparent
    }
    val fg = when (kind) {
        TbKind.Edit -> C.edit2
        TbKind.Danger -> C.danger
        TbKind.Normal -> C.text2
    }
    Box(
        modifier = Modifier
            .height(S.tbH)
            .clip(RoundedCornerShape(S.r))
            .background(bg)
            .clickableNoRipple(onClick)
            .padding(horizontal = 9.dp),
        contentAlignment = Alignment.Center,
    ) { T(label, color = fg, size = S.fs12, bold = true) }
}

/** 工具栏的竖分隔线（`.vsep`）。 */
@Composable
fun VSep() = Box(
    Modifier
        .padding(horizontal = 4.dp)
        .width(1.dp)
        .height(18.dp)
        .background(C.border)
)

/** 小徽章（`.badge` / `.badge.hist`）。 */
@Composable
fun Badge(label: String, hist: Boolean = false) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(S.r8))
            .background(if (hist) C.editSoft else C.bgBar)
            .padding(horizontal = 7.dp, vertical = 1.dp),
    ) { T(label, color = if (hist) C.edit2 else C.text2, size = S.fs11) }
}

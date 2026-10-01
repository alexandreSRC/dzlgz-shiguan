package com.shiguan.pad.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.shiguan.pad.data.PersonData

/**
 * 人物页 —— 严格照 `_stats/proto.html` 的结构：
 * 顶栏(36) / 工具栏(38) / 三栏(左 265 · 中弹性 · 右 470) / 状态栏(24)。
 */
@Composable
fun PersonScreen(d: PersonData) {
    var sel by remember(d.ts) { mutableStateOf(0) }

    Column(Modifier.fillMaxSize().background(C.bgApp)) {
        TopBar(d)
        ToolBar()
        Row(Modifier.weight(1f).fillMaxWidth()) {
            SidePanel(d) { sel = it }
            TablePane(d, sel) { sel = it }
            DetailCard(d.rows.getOrNull(sel), d)
        }
        StatusBar(d)
    }
}

/** 顶栏：品牌 + 页签 + 右侧胶囊。 */
@Composable
private fun TopBar(d: PersonData) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(S.topbar)
            .background(C.bgBar)
            .padding(horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // 品牌块：「史」22×22 绿底白字 + 名称 + 版本胶囊
        Box(
            Modifier
                .size(22.dp)
                .clip(RoundedCornerShape(S.r))
                .background(C.accent),
            contentAlignment = Alignment.Center,
        ) { T("史", color = C.accentOn, size = S.fs13) }
        Spacer(Modifier.width(6.dp))
        T("大周列国志 · 史馆", color = C.text, size = S.fs13, bold = true)
        Spacer(Modifier.width(6.dp))
        Box(
            Modifier
                .clip(RoundedCornerShape(S.r8))
                .background(C.accentSoft)
                .padding(horizontal = 6.dp, vertical = 1.dp),
        ) { T("2.0 版", color = C.accent, size = S.fs10, bold = true) }

        Spacer(Modifier.width(8.dp))

        // 页签：大块矩形，选中 = 整块青绿底（照 Tk）
        Row(Modifier.fillMaxHeight()) {
            Tab("人物", on = true)
            Tab("家谱", on = false)
            Tab("世界", on = false)
            Tab("表格", on = false)
        }

        Spacer(Modifier.weight(1f))
        Pill("存档", d.book)
        Spacer(Modifier.width(8.dp))
        Pill("⟲ 续谱", rec = true)
        Spacer(Modifier.width(8.dp))
        Pill("⚙")
    }
}

/** 工具栏：编辑组 + 查阅组 + 危险组。 */
@Composable
private fun ToolBar() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(S.toolbar)
            .background(C.bgBar)
            .padding(horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ToolBtn("加入族谱", TbKind.Edit)
        VSep()
        ToolBtn("展开全部")
        ToolBtn("字段说明")
        ToolBtn("重新载入")
        VSep()
        ToolBtn("清空封国", TbKind.Danger)
    }
}

/** 状态栏：统计句统一落这一处（规约：不要散落各处）。 */
@Composable
private fun StatusBar(d: PersonData) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(S.statusbar)
            .background(C.bgBar)
            .padding(horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusItem("实录", "${d.record}") { Spacer(Modifier.width(12.dp)) }
        StatusItem("谱牒", d.book) { Spacer(Modifier.width(12.dp)) }
        StatusItem("史实", "${d.stats.firstOrNull()?.second ?: 0}") {
            Spacer(Modifier.width(12.dp))
        }
        StatusItem("实录槽", d.slot) { Spacer(Modifier.width(12.dp)) }
        StatusItem("谱牒档", d.book) { Spacer(Modifier.width(12.dp)) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            T("共 ", color = C.text3, size = S.fs11)
            T("${d.total}", color = C.text, size = S.fs11, bold = true)
            T(" 条，当前显示 ", color = C.text3, size = S.fs11)
            T("${d.rows.size}", color = C.text, size = S.fs11, bold = true)
            T(" 条", color = C.text3, size = S.fs11)
        }
    }
}

@Composable
private fun StatusItem(k: String, v: String, after: @Composable () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        T(k, color = C.text3, size = S.fs11)
        Spacer(Modifier.width(4.dp))
        Text(
            text = v,
            color = C.text,
            fontSize = S.fs11,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
        )
    }
    after()
}

package com.shiguan.pad.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 配色与尺寸 —— **全部照 Tkinter 主题的实测真值**，不是照图目测。
 *
 * 规约（shiguan-conventions）：对接/复刻别人的界面，"看着像"不算，
 * 要跟被复刻方同源取数。上一轮我用目测值把 accent 写成 #2f7f74，
 * 实测 Tk 是 #1f6b4f —— 所以这里每个色值都来自探针读出的 theme 对象。
 */
object C {
    // 底色 / 面板
    val bgApp = Color(0xFFF2ECDC)
    val bgPanel = Color(0xFFF8F4E8)
    val bgCard = Color(0xFFFDFAEE)
    val bgBar = Color(0xFFF8F4E8)
    val bgInput = Color(0xFFFFFFFF)
    val border = Color(0xFFDDD0B8)
    val border2 = Color(0xFFE8E0CC)

    // 文字
    val text = Color(0xFF2A1A0A)
    val text2 = Color(0xFF5A4A38)
    val text3 = Color(0xFF8A7A64)

    // 语义色
    val accent = Color(0xFF1F6B4F)          // 青绿 = 查阅（人物/世界）
    val accentSoft = Color(0xFFDCEBE2)
    val accentOn = Color(0xFFFFFFFF)
    val edit = Color(0xFFA8781F)            // 橙金 = 编辑（家谱/时间轴/表格）
    val edit2 = Color(0xFF7A5518)
    val editSoft = Color(0xFFF2E3C2)
    val spouse = Color(0xFFC2417A)          // 品红 = 女性
    val danger = Color(0xFFC0392B)          // 正红 = 危险
    val dangerSoft = Color(0xFFF8E6E3)
    val dead = Color(0xFF9A938A)            // 灰 = 已故
    val deadBg = Color(0xFFEFECE6)
}

/**
 * 尺寸 —— 单位换算：**1 CSS px（HTML 原型）= 1 dp**。
 *
 * 依据：HTML 原型按 1280 CSS px 宽设计；常见平板
 * （1920×1200 @240dpi、2560×1600 @320dpi）的逻辑宽度**正好都是 1280dp**，
 * 所以 dp 直用 = 与原型 1:1，不需要额外缩放系数。
 */
object S {
    val topbar = 36.dp
    val toolbar = 38.dp
    val statusbar = 24.dp

    val side = 265.dp                        // 左栏
    val right = 470.dp                       // 详情卡栏
    val pad = 6.dp

    val tabH = 36.dp
    val tabPadH = 15.dp
    val pillH = 24.dp
    val tbH = 24.dp
    val actH = 23.dp
    val rowH = 19.dp                         // 表格行高（Tk 实测）
    val headH = 24.dp

    val r = 4.dp                             // 小圆角
    val r6 = 6.dp                            // 卡片圆角
    val r8 = 8.dp                            // 徽章/胶囊

    // 字号（HTML 原型的 11.5 / 12 / 12.5 / 13 px）
    val fs10 = 10.sp
    val fs11 = 11.sp
    val fs115 = 11.5.sp
    val fs12 = 12.sp
    val fs125 = 12.5.sp
    val fs13 = 13.sp
}

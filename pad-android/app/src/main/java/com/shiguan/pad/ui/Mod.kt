package com.shiguan.pad.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed

/**
 * 无涟漪点击。
 *
 * 桌面原型里按钮是**平的、不闪**的；Compose 默认的涟漪在平板上很扎眼，
 * 与"严格按原型实现"不符，所以统一去掉。
 */
fun Modifier.clickableNoRipple(onClick: () -> Unit): Modifier = composed {
    clickable(
        indication = null,
        interactionSource = remember { MutableInteractionSource() },
        onClick = onClick,
    )
}

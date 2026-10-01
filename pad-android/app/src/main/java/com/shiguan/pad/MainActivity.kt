package com.shiguan.pad

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.shiguan.pad.data.ApiClient
import com.shiguan.pad.data.PersonData
import com.shiguan.pad.ui.C
import com.shiguan.pad.ui.PersonScreen
import com.shiguan.pad.ui.S
import com.shiguan.pad.ui.T
import com.shiguan.pad.ui.clickableNoRipple

/**
 * 史馆 · 平板入口。
 *
 * ★ 数据来自 PC 的 `tools/pad_server.py`（局域网 HTTP）—— 数据口径与
 *   Tkinter **同源**（服务端从程序渲染好的表格里取），App 只负责显示。
 *
 * 失败时给**明确提示 + 重试**，而不是空白页（照规约：错误要说清楚）。
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 平板常亮：查谱是长时间阅读场景
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        setContent {
            var data by remember { mutableStateOf<PersonData?>(null) }
            var err by remember { mutableStateOf<String?>(null) }
            var busy by remember { mutableStateOf(true) }
            var tick by remember { mutableStateOf(0) }

            LaunchedEffect(tick) {
                busy = true
                err = null
                try {
                    data = if (tick == 0) ApiClient.fetchData() else ApiClient.reload()
                } catch (e: Exception) {
                    err = e.message ?: e.toString()
                    data = null
                }
                busy = false
            }

            Box(Modifier.fillMaxSize().background(C.bgApp)) {
                val dd = data
                if (dd != null) PersonScreen(dd) else Loading(err, busy) { tick++ }
            }
        }
    }

    /** 加载 / 出错态。 */
    @Composable
    private fun Loading(err: String?, busy: Boolean, retry: () -> Unit) {
        Column(
            Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            if (err == null) {
                T(if (busy) "正在从 PC 取数…" else "没有数据",
                    color = C.text2, size = S.fs13)
                Spacer(Modifier.height(6.dp))
                T("服务器：${ApiClient.baseUrl}", color = C.text3, size = S.fs115)
            } else {
                T("连不上 PC 的数据服务", color = C.danger, size = S.fs13)
                Spacer(Modifier.height(6.dp))
                T("地址：${ApiClient.baseUrl}", color = C.text2, size = S.fs115)
                Spacer(Modifier.height(2.dp))
                Text(
                    text = err,
                    color = C.text3,
                    fontSize = S.fs11,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(horizontal = 24.dp),
                )
                Spacer(Modifier.height(10.dp))
                T("先在 PC 上跑 Start_平板服务.bat，确认两台机在同一 WiFi",
                    color = C.text2, size = S.fs115)
                Spacer(Modifier.height(10.dp))
                Box(
                    Modifier
                        .clip(RoundedCornerShape(S.r))
                        .background(C.accent)
                        .clickableNoRipple(retry)
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                ) {
                    T("重试", color = C.accentOn, size = S.fs13, bold = true)
                }
            }
        }
    }
}

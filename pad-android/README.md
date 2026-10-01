# 史馆 · 平板（安卓）

面向平板的原生前端（Kotlin + Jetpack Compose），**严格照 `_stats/proto.html` 实现**
（尺寸、配色、结构一一对应）。数据由 PC 上的 `tools/pad_server.py` 通过局域网提供。

## 一、跑起来（三步）

1. **PC 起服务**：双击项目根目录的 `Start_平板服务.bat`
   （首次取数约 15 秒；窗口里会打印平板要填的地址，形如 `http://192.168.3.41:8801`）
2. **编译安装**（已构建过一次，改代码后重跑）：
   ```powershell
   $env:JAVA_HOME='D:\Java\jdk-21.0.9+10'
   cd "D:\Desktop\Ongoing apps\大周列国志·史馆\pad-android"
   D:\Gradle\gradle-8.11.1\bin\gradle.bat :app:assembleDebug
   D:\Android\platform-tools\adb.exe install -r app\build\outputs\apk\debug\app-debug.apk
   ```
3. **打开 App**。连不上会显示明确提示（地址 + 排查建议），点「重试」。

> 服务器地址目前写在 `data/ApiClient.kt` 的 `baseUrl`，默认 `http://192.168.3.41:8801`。
> 换网络/换机器要改这一行重编译（后续可做设置界面）。

## 二、目录

```
pad-android/
├── app/src/main/java/com/shiguan/pad/
│   ├── MainActivity.kt          入口：取数 + 加载/出错页
│   ├── data/
│   │   ├── Model.kt             /api/data 的载荷（字段名与服务端一一对应）
│   │   └── ApiClient.kt         HttpURLConnection 客户端（无第三方库）
│   └── ui/
│       ├── Colors.kt            ★ 配色与尺寸（Tk 主题实测真值 + 1px=1dp）
│       ├── Mod.kt               无涟漪点击（原型按钮是平的）
│       ├── Chrome.kt            顶栏页签 / 胶囊 / 工具栏按钮 / 徽章
│       ├── SidePanel.kt         左栏 265dp：人物 / 筛选 / 等级 / 命中 / 搜索
│       ├── TablePane.kt         中栏：标题行 + 表格（列宽用服务端实测值）
│       ├── DetailCard.kt        右栏 470dp：6 列网格的详情卡
│       └── PersonScreen.kt      组装：顶栏36 / 工具栏38 / 三栏 / 状态栏24
└── app/src/main/res/            主题、明文 HTTP 放行（连 PC 必需）
```

## 三、两条纪律（照 `shiguan-conventions`）

1. **同源取数**：界面上的每个数字、列宽、颜色都来自被复刻方，
   客户端**不自己重算**。改口径要改服务端（`tools/pad_data.py`），不要在 App 里另算一套。
   —— 曾因自己按字段算「在世」，得出 5182，而 Tk 真值是 3931。
2. **量不要算**：需要尺寸/位置就先量（`pv.table.column(c,'width')`、`theme` 对象），
   别照截图目测。本轮目测的三处配色全偏（accent 猜 `#2f7f74`，真值 `#1f6b4f`）。

## 四、已知事项

- **工程路径含中文**（`大周列国志·史馆`）：AGP 默认拒建，已在 `gradle.properties`
  里按官方提示关掉检查（`android.overridePathCheck=true`）。
  若后续出现诡异的资源/编译错误，**第一嫌疑是路径** —— 把 `pad-android` 整个移到
  纯 ASCII 路径（如 `D:\ShiguanPad`）即可，无需改代码。
- **尺寸基准 1 CSS px = 1 dp**：原型按 1280 CSS px 宽设计，
  常见平板（1920×1200@240dpi / 2560×1600@320dpi）逻辑宽正好 1280dp ⇒ 1:1。
  **手机上（如 1440×2560@360dpi：竖屏 640dp / 横屏 1137dp）会挤** —— 三栏共需 735dp 固定宽，
  横屏能放下但比原型紧，竖屏放不下。平板才是目标设备。
- 详情卡右栏（父系/母系/配偶…）目前显示「—」，因为服务端还没抽亲属数据 —— 下一步补。

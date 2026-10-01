rem 大周列国志 · 史馆 —— 无黑框启动器
rem 只负责隐藏窗口调用 Start.bat，找 Python 的逻辑全在 .bat 里。
Option Explicit
Dim shell, fso, here, batPath, rc
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(here, "Start.bat")
If Not fso.FileExists(batPath) Then
    MsgBox "找不到 Start.bat，请确认它和 Start.vbs 在同一个文件夹里。", 16, "大周列国志 · 史馆"
    WScript.Quit 1
End If
rc = shell.Run("""" & batPath & """", 0, True)
If rc <> 0 Then
    MsgBox "程序未能正常启动（返回码 " & rc & "）。" & vbCrLf & vbCrLf & "请改用 Start.bat 双击运行，可以看到详细报错。", 16, "大周列国志 · 史馆"
End If

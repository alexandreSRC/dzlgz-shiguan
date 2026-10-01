rem  Da Zhou Lie Guo Zhi - Shiguan  --  silent launcher (no console window)
rem  Kept pure ASCII on purpose: WSH parses .vbs with the system ANSI code
rem  page, so non-ASCII characters here can break the script.
rem  This file only hides the console window and calls Start.bat;
rem  the Python lookup logic lives in Start.bat alone.
Option Explicit
Dim shell, fso, here, batPath, rc
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(here, "Start.bat")
If Not fso.FileExists(batPath) Then
    MsgBox "Start.bat not found." & vbCrLf & vbCrLf & "Please keep Start.vbs and Start.bat in the same folder.", 16, "Shiguan"
    WScript.Quit 1
End If
rc = shell.Run("""" & batPath & """", 0, True)
If rc <> 0 Then
    MsgBox "The program failed to start (exit code " & rc & ")." & vbCrLf & vbCrLf & "Run Start.bat directly instead to see the detailed error.", 16, "Shiguan"
End If
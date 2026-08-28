Option Explicit
' ============================================
'  إيقاف نظام الموارد البشرية (Hidden)
'  يوقف السيرفر ويعيد تشغيله
' ============================================
On Error Resume Next
Dim WshShell, fso, base, pid, res
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)

' Read PID file and kill the server process
If fso.FileExists(base + "\server.pid") Then
    Dim ts
    Set ts = fso.OpenTextFile(base + "\server.pid", 1)
    pid = Trim(ts.ReadLine())
    ts.Close
    If Len(pid) > 0 Then
        res = WshShell.Run("cmd /c taskkill /PID " & pid & " /F >nul 2>&1", 0, True)
    End If
    fso.DeleteFile base + "\server.pid", True
End If

On Error GoTo 0
WScript.Quit
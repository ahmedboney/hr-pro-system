Option Explicit
' ============================================
'  مشغل نظام الموارد البشرية (Hidden / No CMD)
'  يعمل بصمت تام ويفتح المتصفح تلقائياً
' ============================================
On Error Resume Next
Dim WshShell, fso, base, pyw, res, cmdLine
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = base

' --- Find pythonw.exe ---
pyw = ""
On Error Resume Next
res = WshShell.Run("cmd /c where pythonw > " + base + "\logs\_pyw.tmp", 0, True)
If Err.Number = 0 Then
    If fso.FileExists(base + "\logs\_pyw.tmp") Then
        Dim ts, line
        Set ts = fso.OpenTextFile(base + "\logs\_pyw.tmp", 1)
        line = ts.ReadLine()
        ts.Close
        fso.DeleteFile base + "\logs\_pyw.tmp", True
        If fso.FileExists(line) Then pyw = line
    End If
End If
On Error GoTo 0

' --- Fallback paths ---
If Len(pyw) = 0 Then
    If fso.FileExists("C:\Program Files\Python311\pythonw.exe") Then pyw = "C:\Program Files\Python311\pythonw.exe"
End If
If Len(pyw) = 0 Then
    If fso.FileExists("C:\Program Files (x86)\Python311\pythonw.exe") Then pyw = "C:\Program Files (x86)\Python311\pythonw.exe"
End If
If Len(pyw) = 0 Then
    If fso.FileExists(Environ("LOCALAPPDATA") + "\Programs\Python\Python311\pythonw.exe") Then pyw = Environ("LOCALAPPDATA") + "\Programs\Python\Python311\pythonw.exe"
End If

If Len(pyw) = 0 Then
    MsgBox "لم يتم العثور على python من فضلك تأكد من تثبيت Python 3", 48, "نظام الموارد البشرية"
    WScript.Quit
End If

' --- Launch hidden (1 = window style hidden, False = don't wait) ---
cmdLine = """" & pyw & """ """ & base & "\run_server.py"""
res = WshShell.Run(cmdLine, 0, False)

' --- If no browser opened, open it after a short delay ---
res = WshShell.Run("cmd /c timeout /t 3 /nobreak >nul & start http://127.0.0.1:8080", 0, True)
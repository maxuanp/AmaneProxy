' Amane proxy dispatcher - start with no console window (ASCII only).
' All paths are resolved relative to this file, so the folder can live anywhere.
' __PYTHONW__ is replaced with the real pythonw.exe path by install-autostart.ps1.
' If that was never done, we try pythonw.exe / pyw.exe from PATH.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
script = root & "\amaneproxy.py"

pythonw = "__PYTHONW__"
If pythonw = "__PYTHONW__" Then pythonw = "pythonw.exe"

On Error Resume Next
sh.Run """" & pythonw & """ """ & script & """", 0, False
If Err.Number = 0 Then WScript.Quit 0

Err.Clear
sh.Run """pyw.exe"" -3 """ & script & """", 0, False
If Err.Number = 0 Then WScript.Quit 0

Err.Clear
' last resort: run with a console window so the error is visible
sh.Run """python.exe"" """ & script & """", 1, False
If Err.Number <> 0 Then
  MsgBox "Cannot start Python." & vbCrLf & vbCrLf & _
         "Install Python 3.10+ (tick 'Add python.exe to PATH'), then run" & vbCrLf & _
         "install-autostart.ps1 - or edit this file and put the full path" & vbCrLf & _
         "of pythonw.exe into it.", 48, "AmaneProxy"
End If

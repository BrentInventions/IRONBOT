' Recon Sniper — no CMD window. Always this Desktop folder, never trading\mark2.
Option Explicit
Dim fso, sh, here, root, env, stamp, errn
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(here)
sh.CurrentDirectory = root
Set env = sh.Environment("Process")
env("MARK2_OFFLINE_OK") = "1"
env("PYTHONNOUSERSITE") = "1"
env("PYTHONPATH") = root
env("MARK2_FRONTEND") = here & "\frontend"
env("RECON_APP_HOME") = root

If Not fso.FolderExists(here & "\logs") Then fso.CreateFolder here & "\logs"
Set stamp = fso.CreateTextFile(here & "\logs\last_launch.txt", True)
stamp.WriteLine Now & " launch-bot.vbs cwd=" & root

On Error Resume Next
Err.Clear
' pythonw first — pyw.exe can exit without ever opening the HUD.
sh.Run "pythonw.exe -m mark2", 0, False
errn = Err.Number
stamp.WriteLine "pythonw.exe -m mark2 err=" & errn
If errn <> 0 Then
  Err.Clear
  sh.Run "pyw.exe -3 -m mark2", 0, False
  stamp.WriteLine "pyw.exe -3 -m mark2 err=" & Err.Number
End If
stamp.Close

' watchdog-hidden.vbs
'
' Launches scripts\voice-watchdog.ps1 with NO visible window.
' Prevents the 5-min PowerShell flash that shows in the taskbar.
'
' Identical pattern to start-daemon-hidden.vbs. Window style 0 =
' completely hidden; no taskbar entry, no console flicker.

Set fs = CreateObject("Scripting.FileSystemObject")
strDir = fs.GetParentFolderName(WScript.ScriptFullName)
ps1Path = strDir & "\voice-watchdog.ps1"

Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -NonInteractive -File """ & ps1Path & """", 0, True

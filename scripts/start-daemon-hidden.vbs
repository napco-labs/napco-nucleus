' start-daemon-hidden.vbs
'
' Launches scripts\start-daemon.bat with NO visible window.
' Designed to be the Scheduled Task action so devs don't see a cmd
' window appear at logon. Logs still go to logs\voice_daemon.log.
'
' WshShell.Run intWindowStyle codes:
'   0 = hidden (no console at all -- what we want)
'   1 = normal
'   7 = minimized (would still flash a window briefly)
'
' Final True = wait for the launched process to exit. This keeps
' wscript.exe alive for the duration of the daemon so Task Scheduler
' tracks it correctly and "restart on failure" actually fires when
' the daemon dies.

Set fs = CreateObject("Scripting.FileSystemObject")
strDir = fs.GetParentFolderName(WScript.ScriptFullName)
batPath = strDir & "\start-daemon.bat"

Set sh = CreateObject("WScript.Shell")
sh.Run Chr(34) & batPath & Chr(34), 0, True

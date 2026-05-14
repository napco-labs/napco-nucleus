' push-chat-hidden.vbs
'
' Launches `python -m teams.push_chat <args>` with NO visible window.
' Designed to be the Scheduled Task action for the three chat-push
' tasks (Day, Transition, Evening) so devs don't see a cmd window
' flash every 30 min during the evening peak.
'
' All command-line arguments passed to this VBS are forwarded to
' teams.push_chat -- typically `--last-minutes 120` (or 90 / 30).
'
' Output goes to logs\chat_push.log (append mode) so push history is
' readable: `Get-Content logs\chat_push.log -Tail 50`.
'
' WshShell.Run intWindowStyle:
'   0 = hidden  (what we want)
'   1 = normal
'   7 = minimized (still flashes briefly)

Set fs = CreateObject("Scripting.FileSystemObject")
strDir   = fs.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fs.GetParentFolderName(strDir)
logDir   = repoRoot & "\logs"
If Not fs.FolderExists(logDir) Then fs.CreateFolder(logDir)
logFile = logDir & "\chat_push.log"

' Pass through every CLI arg this VBS received (Task Scheduler supplies
' --last-minutes <N> per task).
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next

' Resolve python in this order: venv -> python.exe on PATH -> py -3 launcher.
' VBS can't probe PATH cleanly, so we let cmd's `where` do it. The
' launcher fallback matters because fresh dev machines often have only
' the Python Launcher (py.exe) on PATH, not bare python.exe.
pythonExe = repoRoot & "\.venv\Scripts\python.exe"
If fs.FileExists(pythonExe) Then
    pyInvoke = Chr(34) & pythonExe & Chr(34) & " -u"
Else
    ' `where python` exit code is 0 if python.exe is on PATH.
    Set tmpShell = CreateObject("WScript.Shell")
    whereRC = tmpShell.Run("cmd /c where python.exe >nul 2>&1", 0, True)
    If whereRC = 0 Then
        pyInvoke = "python -u"
    Else
        pyInvoke = "py -3 -u"
    End If
End If

' cmd /c wrapper so we can redirect stdout+stderr to the log file.
' Use `>>` (append) so multiple runs in a day accumulate.
quoted_log = Chr(34) & logFile & Chr(34)
cmdLine = "cmd /c " & Chr(34) & pyInvoke & " -m teams.push_chat" & args & _
          " >> " & quoted_log & " 2>&1" & Chr(34)

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = repoRoot

' Write a small "tick" marker into the log so it's easy to tell when
' a run started from when it ended.
Set logStream = fs.OpenTextFile(logFile, 8, True)  ' 8 = append, True = create if missing
logStream.WriteLine ""
logStream.WriteLine "============================================================"
logStream.WriteLine "[push-chat-hidden.vbs] " & Now & "  args:" & args
logStream.WriteLine "============================================================"
logStream.Close

' 0 = hidden window, True = wait for completion so Task Scheduler sees
' the real exit code.
sh.Run cmdLine, 0, True

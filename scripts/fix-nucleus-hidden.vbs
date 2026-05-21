' fix-nucleus-hidden.vbs
'
' At-logon launcher for the Self-Heal scheduled task. Runs
' scripts\fix-nucleus.bat --quiet with NO visible console so the dev
' isn't interrupted at every login. All output lands in
' logs\fix-nucleus.log -- tail it from the repo with:
'   Get-Content logs\fix-nucleus.log -Wait -Tail 50
'
' Repo location resolution order:
'   1. %NN% (set by fix-nucleus.bat on first run via setx)
'   2. Parent of this script's folder (works if dev keeps the repo
'      intact and the VBS is invoked from inside scripts\)
'
' WshShell.Run intWindowStyle:  0 = hidden  (what we want)
' Final True = wait for cmd to exit so Task Scheduler tracks the run.

Set fs = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

' Try %NN% first
nn = ""
On Error Resume Next
nn = sh.ExpandEnvironmentStrings("%NN%")
On Error Goto 0
If nn = "%NN%" Then nn = ""

' Fallback: script lives at <repo>\scripts\fix-nucleus-hidden.vbs
If nn = "" Or Not fs.FolderExists(nn) Then
    nn = fs.GetParentFolderName(fs.GetParentFolderName(WScript.ScriptFullName))
End If

batPath = nn & "\scripts\fix-nucleus.bat"
logDir = nn & "\logs"
If Not fs.FolderExists(logDir) Then fs.CreateFolder(logDir)
logPath = logDir & "\fix-nucleus.log"

' cmd /c "..." --quiet >> log 2>&1
'   - append mode so successive logons accumulate history
'   - quoted around the bat path because Atik's repo has a space
cmdLine = "cmd /c """"" & batPath & """"" & " --quiet >> """ & logPath & """ 2>&1"
sh.Run cmdLine, 0, True

' Hidden launcher for docvault context-menu verbs.
'
' wscript.exe is a GUI-subsystem host, so it shows no window of its own. We
' use it to spawn the target .bat with WindowStyle=0 (hidden); the spawned
' cmd.exe and any children it launches inherit the hidden console, so the
' user sees no cmd flash when right-clicking "Ingest into docvault" etc.
'
' Args:
'   1)   full path to the .bat to run
'   2+)  args to forward to the .bat (e.g. the file or folder path from %1)
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count < 1 Then WScript.Quit 1
cmdLine = Chr(34) & WScript.Arguments(0) & Chr(34)
For i = 1 To WScript.Arguments.Count - 1
    cmdLine = cmdLine & " " & Chr(34) & WScript.Arguments(i) & Chr(34)
Next
' WindowStyle=0 -> hidden, bWaitOnReturn=False -> don't block Explorer.
sh.Run cmdLine, 0, False

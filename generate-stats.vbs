Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pyScript  = fso.BuildPath(scriptDir, "get_stats.py")

Set objShell = CreateObject("WScript.Shell")
objShell.Run "pythonw """ & pyScript & """", 0, True
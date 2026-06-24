Set fso = CreateObject("Scripting.FileSystemObject")
projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)

cmd = "powershell -NoProfile -ExecutionPolicy Bypass -File """ & projectRoot & "\scripts\stop-hidden.ps1"""
CreateObject("WScript.Shell").Run cmd, 0, False

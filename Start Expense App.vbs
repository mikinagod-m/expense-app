Set fso = CreateObject("Scripting.FileSystemObject")
projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)

cmd = "powershell -NoProfile -ExecutionPolicy Bypass -File """ & projectRoot & "\scripts\start-hidden.ps1"" -Lan"
CreateObject("WScript.Shell").Run cmd, 0, False

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")

Do
    WshShell.Run """C:\Users\Admin\AppData\Local\Programs\Python\Python312\pythonw.exe"" """ & scriptDir & "\bot.py""", 0, True
    WScript.Sleep 10000
Loop

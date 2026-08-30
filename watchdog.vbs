Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

vacationDir = "C:\Users\Admin\Desktop\�������\VacationBot"
roleBotDir  = "C:\Users\Admin\Documents\Default Project\discord-role-bot"
pythonw     = "C:\Users\Admin\AppData\Local\Programs\Python\Python312\pythonw.exe"

Function IsRunning(botPath)
    IsRunning = False
    Set colProcesses = GetObject("winmgmts:\\.\root\cimv2").ExecQuery( _
        "SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='pythonw.exe'")
    For Each objProcess in colProcesses
        If InStr(objProcess.CommandLine, botPath) > 0 Then
            IsRunning = True
            Exit Function
        End If
    Next
End Function

Function IsProcAlive(procName)
    IsProcAlive = False
    Set colProcesses = GetObject("winmgmts:\\.\root\cimv2").ExecQuery( _
        "SELECT Name FROM Win32_Process WHERE Name='" & procName & "'")
    For Each objProcess in colProcesses
        If LCase(objProcess.Name) = LCase(procName) Then
            IsProcAlive = True
            Exit Function
        End If
    Next
End Function

Do

    If Not IsProcAlive("xray-oversub.exe") Then
        WshShell.Run """C:\Users\Admin\AppData\Local\Programs\xray\xray-oversub.exe"" -c ""C:\Users\Admin\AppData\Local\Programs\xray\config-oversub.json""", 0, False
    End If

    If Not IsRunning(vacationDir & "\bot.py") Then
        If Not fso.FileExists(vacationDir & "\bot.paused") Then
            WshShell.Run """" & pythonw & """ """ & vacationDir & "\bot.py""", 0, False
        End If
    End If

    If Not IsRunning(roleBotDir & "\bot.py") Then
        If Not fso.FileExists(roleBotDir & "\bot.paused") Then
            WshShell.Run """" & pythonw & """ """ & roleBotDir & "\bot.py""", 0, False
        End If
    End If

    WScript.Sleep 60000
Loop

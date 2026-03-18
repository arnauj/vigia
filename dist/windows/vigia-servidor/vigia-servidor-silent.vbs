' VIGIA Server - Lanzador silencioso (sin ventana de consola)
' Uso: wscript vigia-servidor-silent.vbs [--no-browser]
' Este script lanza vigia-servidor.exe de forma completamente invisible.
' El exe DEBE estar en la subcarpeta server\ junto con su _internal\.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Obtener la carpeta donde esta el .vbs
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' El exe esta en la subcarpeta server\ (con su _internal\)
serverDir = fso.BuildPath(scriptDir, "server")
exePath = fso.BuildPath(serverDir, "vigia-servidor.exe")

' Fallback: misma carpeta que el VBS (para instalaciones simples sin subcarpeta)
If Not fso.FileExists(exePath) Then
    serverDir = scriptDir
    exePath = fso.BuildPath(scriptDir, "vigia-servidor.exe")
End If

' Recoger argumentos adicionales
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next

' Cambiar al directorio del exe antes de ejecutar (para que encuentre _internal\)
WshShell.CurrentDirectory = serverDir

' Run con windowStyle=0 (oculto), waitOnReturn=False
WshShell.Run """" & exePath & """" & args, 0, False

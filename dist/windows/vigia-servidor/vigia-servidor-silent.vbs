' VIGIA Server - Lanzador silencioso (sin ventana de consola)
' Uso: wscript vigia-servidor-silent.vbs [--no-browser]
' Este script lanza vigia-servidor.exe de forma completamente invisible.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Obtener la carpeta donde esta el .vbs
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Construir ruta al exe del servidor
exePath = fso.BuildPath(scriptDir, "vigia-servidor.exe")

' Si no existe en la misma carpeta, buscar en subcarpeta server\
If Not fso.FileExists(exePath) Then
    exePath = fso.BuildPath(scriptDir, "server\vigia-servidor.exe")
End If

' Recoger argumentos adicionales
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next

' Run con windowStyle=0 (oculto), waitOnReturn=False
WshShell.Run """" & exePath & """" & args, 0, False

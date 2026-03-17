' VIGIA Client - Lanzador silencioso (sin ventana de consola)
' Uso: wscript vigia-cliente-silent.vbs [IP] [puerto]
' Este script lanza vigia-cliente.exe de forma completamente invisible.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Obtener la carpeta donde esta el .vbs
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Construir ruta al exe del cliente
exePath = fso.BuildPath(scriptDir, "vigia-cliente.exe")

' Recoger argumentos adicionales (IP del servidor, puerto, etc.)
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next

' Run con windowStyle=0 (oculto), waitOnReturn=False
WshShell.Run """" & exePath & """" & args, 0, False

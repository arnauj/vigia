; ============================================================================
; VIGIA Server - Inno Setup Installer Script
; Genera vigia-server-setup.exe
; Requisito: ejecutar build_windows.bat antes para generar dist\windows\
;
; AUTOARRANQUE: tras instalar, el servidor queda configurado para arrancar solo
; al encender el equipo, sin que el profesor tenga que hacer nada. Se usa la
; clave Run de HKLM apuntando al wrapper .vbs -> cero consola. Sustituye a la
; tarea programada de versiones anteriores, que solo se creaba para la cuenta
; que ejecuto el instalador (si era una cuenta de administrador distinta de la
; del profesor, el servidor no arrancaba nunca).
;
; Instalacion desatendida:  vigia-server-setup.exe /VERYSILENT
; ============================================================================

[Setup]
AppName=VIGIA Server
AppVersion=1.1
AppPublisher=VIGIA
DefaultDirName={autopf}\VIGIA Server
DefaultGroupName=VIGIA
OutputDir=dist\installers
OutputBaseFilename=vigia-server-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
SetupIconFile=img\logo2.ico
UninstallDisplayIcon={app}\img\logo2.ico

[Files]
; Servidor (proceso en segundo plano)
Source: "dist\windows\vigia-servidor\*"; DestDir: "{app}\server"; Flags: ignoreversion recursesubdirs
; Launcher (abre el dashboard sin consola)
Source: "dist\windows\vigia-launcher\*"; DestDir: "{app}\launcher"; Flags: ignoreversion recursesubdirs
; Wrappers VBS silenciosos
Source: "vigia-servidor-silent.vbs"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Menu de inicio: el launcher abre el dashboard (sin consola)
Name: "{group}\VIGIA Server"; Filename: "{app}\launcher\vigia-launcher.exe"; WorkingDir: "{app}\launcher"; IconFilename: "{app}\server\img\logo2.ico"
Name: "{group}\Desinstalar VIGIA Server"; Filename: "{uninstallexe}"
; Escritorio: launcher
Name: "{commondesktop}\VIGIA Server"; Filename: "{app}\launcher\vigia-launcher.exe"; WorkingDir: "{app}\launcher"; IconFilename: "{app}\server\img\logo2.ico"

[Registry]
; AUTOARRANQUE al encender el equipo, para cualquier cuenta que inicie sesion.
; --no-browser: solo levanta Flask; el dashboard lo abre el profesor con el
; icono del escritorio (el launcher detecta el puerto 5000 y lo reutiliza).
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VIGIA Server"; ValueData: "wscript.exe ""{app}\vigia-servidor-silent.vbs"" --no-browser"; Flags: uninsdeletevalue

[Run]
; Abrir puerto 5000 en el firewall de Windows
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""VIGIA Server"" dir=in action=allow protocol=TCP localport=5000"; Flags: runhidden
; Eliminar la tarea programada de versiones anteriores: ahora el autoarranque lo
; gestiona la clave Run de HKLM y tener ambas levantaria dos servidores
; peleandose por el puerto 5000.
Filename: "schtasks"; Parameters: "/Delete /TN ""VIGIA Server"" /F"; Flags: runhidden
; Arrancar ya, sin preguntar. Instalacion normal: el launcher levanta Flask y
; abre el dashboard. Instalacion silenciosa: solo el servidor en segundo plano.
; Son excluyentes a proposito, para no levantar dos Flask sobre el puerto 5000.
Filename: "{app}\launcher\vigia-launcher.exe"; WorkingDir: "{app}\launcher"; Flags: nowait runasoriginaluser skipifsilent
Filename: "wscript.exe"; Parameters: """{app}\vigia-servidor-silent.vbs"" --no-browser"; WorkingDir: "{app}"; Flags: nowait runasoriginaluser; Check: EsInstalacionSilenciosa

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM vigia-servidor.exe"; Flags: runhidden
Filename: "taskkill"; Parameters: "/F /IM vigia-launcher.exe"; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""VIGIA Server"""; Flags: runhidden
Filename: "schtasks"; Parameters: "/Delete /TN ""VIGIA Server"" /F"; Flags: runhidden

[Code]
{ En instalacion silenciosa no hay dashboard que abrir: se arranca solo el
  servidor en segundo plano, igual que hara al encender el equipo. }
function EsInstalacionSilenciosa(): Boolean;
begin
  Result := WizardSilent;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKEY_LOCAL_MACHINE,
      'Software\Microsoft\Windows\CurrentVersion\Run', 'VIGIA Server');
end;

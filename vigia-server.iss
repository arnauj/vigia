; ============================================================================
; VIGIA Server - Inno Setup Installer Script
; Genera vigia-server-setup.exe
; Requisito: ejecutar build_windows.bat antes para generar dist\windows\
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

[Icons]
; Menu de inicio: el launcher abre el dashboard (sin consola)
Name: "{group}\VIGIA Server"; Filename: "{app}\launcher\vigia-launcher.exe"; WorkingDir: "{app}\launcher"
Name: "{group}\Desinstalar VIGIA Server"; Filename: "{uninstallexe}"
; Escritorio: launcher
Name: "{commondesktop}\VIGIA Server"; Filename: "{app}\launcher\vigia-launcher.exe"; WorkingDir: "{app}\launcher"

[Run]
; Abrir puerto 5000 en el firewall de Windows
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""VIGIA Server"" dir=in action=allow protocol=TCP localport=5000"; Flags: runhidden
; Crear tarea programada para auto-arranque al inicio de sesion (servidor en segundo plano, sin navegador)
Filename: "schtasks"; Parameters: "/Create /SC ONLOGON /TN ""VIGIA Server"" /TR """"""{app}\server\vigia-servidor.exe"""""" --no-browser"" /RL HIGHEST /F"; Flags: runhidden

[UninstallRun]
; Matar proceso del servidor antes de desinstalar
Filename: "taskkill"; Parameters: "/F /IM vigia-servidor.exe"; Flags: runhidden
Filename: "taskkill"; Parameters: "/F /IM vigia-launcher.exe"; Flags: runhidden
; Eliminar regla de firewall
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""VIGIA Server"""; Flags: runhidden
; Eliminar tarea programada
Filename: "schtasks"; Parameters: "/Delete /TN ""VIGIA Server"" /F"; Flags: runhidden

[Code]
var
  ResultCode: Integer;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if MsgBox('Iniciar VIGIA Server ahora?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      { Lanzar el launcher: arranca servidor + abre dashboard, sin consola }
      Exec(ExpandConstant('{app}\launcher\vigia-launcher.exe'), '', ExpandConstant('{app}\launcher'), SW_SHOWNORMAL, ewNoWait, ResultCode);
    end;
  end;
end;

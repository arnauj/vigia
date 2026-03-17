; ============================================================================
; VIGIA Client - Inno Setup Installer Script
; Genera vigia-client-setup.exe
; Requisito: ejecutar build_windows.bat antes para generar dist\windows\
; ============================================================================

[Setup]
AppName=VIGIA Client
AppVersion=1.1
AppPublisher=VIGIA
DefaultDirName={autopf}\VIGIA Client
DefaultGroupName=VIGIA
OutputDir=dist\installers
OutputBaseFilename=vigia-client-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
SetupIconFile=img\logo2.ico
UninstallDisplayIcon={app}\img\logo2.ico

[Files]
Source: "dist\windows\vigia-cliente\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
; Wrapper VBS silencioso
Source: "vigia-cliente-silent.vbs"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Menu de inicio: lanza el cliente sin consola
Name: "{group}\VIGIA Client"; Filename: "wscript.exe"; Parameters: """{app}\vigia-cliente-silent.vbs"" {code:GetServerIP}"; WorkingDir: "{app}"; IconFilename: "{app}\img\logo2.ico"
Name: "{group}\Desinstalar VIGIA Client"; Filename: "{uninstallexe}"

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM vigia-cliente.exe"; Flags: runhidden

[UninstallDelete]
Type: files; Name: "{userstartup}\VIGIA Client.lnk"

[Code]
var
  ServerIPPage: TInputQueryWizardPage;
  ResultCode: Integer;

procedure InitializeWizard();
begin
  ServerIPPage := CreateInputQueryPage(wpSelectDir,
    'Configuracion del Servidor',
    'Introduce la IP del servidor VIGIA',
    'El cliente se conectara a este servidor para enviar la pantalla del alumno.');
  ServerIPPage.Add('IP del Servidor:', False);
  ServerIPPage.Values[0] := '192.168.1.2';
end;

function GetServerIP(Param: String): String;
begin
  Result := ServerIPPage.Values[0];
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigDir: String;
  ConfigFile: String;
begin
  if CurStep = ssPostInstall then
  begin
    // Guardar la IP en %APPDATA%\vigia\client.conf
    ConfigDir := ExpandConstant('{userappdata}\vigia');
    ForceDirectories(ConfigDir);
    ConfigFile := ConfigDir + '\client.conf';
    SaveStringToFile(ConfigFile, ServerIPPage.Values[0], False);

    // Crear acceso directo en carpeta de inicio → usa wscript + .vbs = CERO consola
    CreateShellLink(
      ExpandConstant('{userstartup}\VIGIA Client.lnk'),
      'VIGIA Client',
      'wscript.exe',
      ExpandConstant('"{app}\vigia-cliente-silent.vbs" ') + ServerIPPage.Values[0],
      ExpandConstant('{app}'),
      '', 0, SW_SHOWNORMAL);

    // Iniciar ahora (sin consola, via .vbs)
    if MsgBox('Iniciar VIGIA Client ahora?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      Exec('wscript.exe',
           ExpandConstant('"{app}\vigia-cliente-silent.vbs" ') + ServerIPPage.Values[0],
           ExpandConstant('{app}'),
           SW_SHOWNORMAL, ewNoWait, ResultCode);
    end;
  end;
end;

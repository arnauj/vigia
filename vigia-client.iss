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

[Icons]
Name: "{group}\VIGIA Client"; Filename: "{app}\vigia-cliente.exe"; Parameters: "{code:GetServerIP}"; WorkingDir: "{app}"
Name: "{group}\Desinstalar VIGIA Client"; Filename: "{uninstallexe}"

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

    // Crear acceso directo en carpeta de inicio
    CreateShellLink(
      ExpandConstant('{userstartup}\VIGIA Client.lnk'),
      'VIGIA Client',
      ExpandConstant('{app}\vigia-cliente.exe'),
      ServerIPPage.Values[0],
      ExpandConstant('{app}'),
      '', 0, SW_SHOWNORMAL);

    // Preguntar si iniciar ahora
    if MsgBox('Iniciar VIGIA Client ahora?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      Exec(ExpandConstant('{app}\vigia-cliente.exe'),
           ServerIPPage.Values[0], ExpandConstant('{app}'),
           SW_SHOW, ewNoWait, ResultCode);
    end;
  end;
end;

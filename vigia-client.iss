; ============================================================================
; VIGIA Client - Inno Setup Installer Script
; Genera vigia-client-setup.exe
; Requisito: ejecutar build_windows.bat antes para generar dist\windows\
;
; AUTOARRANQUE: tras instalar, el cliente queda configurado para arrancar solo
; al encender el equipo, con CUALQUIER cuenta que inicie sesion, sin que el
; usuario tenga que hacer nada. Se usa la clave Run de HKLM (maquina completa,
; no solo el usuario que instalo) apuntando al wrapper .vbs -> cero consola.
;
; Instalacion desatendida (despliegue en aula):
;   vigia-client-setup.exe /VERYSILENT /SERVERIP=192.168.1.2
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

[Registry]
; AUTOARRANQUE para TODOS los usuarios del equipo. La clave Run de HKLM se
; ejecuta en la sesion interactiva de quien inicie sesion, que es justo lo que
; necesita el cliente (captura de pantalla + ventanas Tk).
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VIGIA Client"; ValueData: "{code:GetRunCommand}"; Flags: uninsdeletevalue

[Run]
; Arrancar ya, sin preguntar. runasoriginaluser = en la sesion del usuario real,
; no en el contexto elevado del instalador.
Filename: "wscript.exe"; Parameters: """{app}\vigia-cliente-silent.vbs"" {code:GetServerIP}"; WorkingDir: "{app}"; Flags: nowait runasoriginaluser

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM vigia-cliente.exe"; Flags: runhidden

[UninstallDelete]
; Acceso directo de arranque de versiones anteriores
Type: files; Name: "{userstartup}\VIGIA Client.lnk"
Type: filesandordirs; Name: "{commonappdata}\vigia"

[Code]
var
  ServerIPPage: TInputQueryWizardPage;

{ IP pasada por linea de comandos (/SERVERIP=x.x.x.x) para despliegue desatendido }
function ParamServerIP(): String;
begin
  Result := Trim(ExpandConstant('{param:SERVERIP|}'));
end;

procedure InitializeWizard();
begin
  ServerIPPage := CreateInputQueryPage(wpSelectDir,
    'Configuracion del Servidor',
    'Introduce la IP del servidor VIGIA',
    'El cliente se conectara a este servidor para enviar la pantalla del alumno.' + #13#10 +
    'Tras instalar, VIGIA arrancara solo cada vez que se encienda el equipo.');
  ServerIPPage.Add('IP del Servidor:', False);
  if ParamServerIP() <> '' then
    ServerIPPage.Values[0] := ParamServerIP()
  else
    ServerIPPage.Values[0] := '192.168.1.2';
end;

{ Con /SERVERIP=... no hace falta preguntar nada }
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ServerIPPage.ID) and (ParamServerIP() <> '');
end;

function GetServerIP(Param: String): String;
begin
  Result := Trim(ServerIPPage.Values[0]);
  if Result = '' then
    Result := ParamServerIP();
end;

{ Valor de la clave Run: wscript + .vbs + IP = arranque invisible al encender }
function GetRunCommand(Param: String): String;
begin
  Result := 'wscript.exe "' + ExpandConstant('{app}') + '\vigia-cliente-silent.vbs" ' + GetServerIP('');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  UserConfigDir: String;
  CommonConfigDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    { Config de MAQUINA: la lee cualquier cuenta que inicie sesion. Es la que
      permite que el autoarranque funcione tambien para alumnos distintos del
      administrador que instalo. }
    CommonConfigDir := ExpandConstant('{commonappdata}\vigia');
    ForceDirectories(CommonConfigDir);
    SaveStringToFile(CommonConfigDir + '\client.conf', GetServerIP(''), False);

    { Config por usuario: compatibilidad con instalaciones anteriores }
    UserConfigDir := ExpandConstant('{userappdata}\vigia');
    ForceDirectories(UserConfigDir);
    SaveStringToFile(UserConfigDir + '\client.conf', GetServerIP(''), False);

    { Limpiar el acceso directo de arranque por usuario de versiones anteriores:
      ahora el autoarranque lo gestiona la clave Run de HKLM y tener los dos
      lanzaria el cliente dos veces. }
    DeleteFile(ExpandConstant('{userstartup}\VIGIA Client.lnk'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKEY_LOCAL_MACHINE,
      'Software\Microsoft\Windows\CurrentVersion\Run', 'VIGIA Client');
end;

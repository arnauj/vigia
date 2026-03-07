#define MyAppName "VIGIA Client"
#ifndef AppVersion
  #define AppVersion "1.1"
#endif
#ifndef SourceDir
  #define SourceDir "..\\dist\\windows\\bin\\VIGIA-Client"
#endif
#ifndef OutputDir
  #define OutputDir "..\\dist\\windows\\installers"
#endif

[Setup]
AppId={{B4F20D95-4EFA-4C4E-A1A2-5A47749FBA72}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher=VIGIA
DefaultDirName={autopf}\\VIGIA Client
DefaultGroupName={#MyAppName}
OutputDir={#OutputDir}
OutputBaseFilename=vigia-client-{#AppVersion}-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "autostart"; Description: "Iniciar VIGIA Client al arrancar Windows"; GroupDescription: "Inicio automático:"

[Files]
Source: "{#SourceDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\\VIGIA Client"; Filename: "{app}\\VIGIA-Client.exe"
Name: "{commondesktop}\\VIGIA Client"; Filename: "{app}\\VIGIA-Client.exe"; Tasks: desktopicon
Name: "{commonstartup}\\VIGIA Client"; Filename: "{app}\\VIGIA-Client.exe"; Tasks: autostart

[Run]
Filename: "{app}\\VIGIA-Client.exe"; Description: "Iniciar VIGIA Client"; Flags: nowait postinstall skipifsilent

[Code]
var
  ServerIpPage: TInputQueryWizardPage;

function IsValidIPv4(const Value: string): Boolean;
var
  I: Integer;
  DotCount: Integer;
  Part: string;
  Num: Integer;
begin
  Result := False;
  DotCount := 0;
  Part := '';

  for I := 1 to Length(Value) do
  begin
    if Value[I] = '.' then
    begin
      if Part = '' then Exit;
      Num := StrToIntDef(Part, -1);
      if (Num < 0) or (Num > 255) then Exit;
      Inc(DotCount);
      Part := '';
    end
    else if (Value[I] >= '0') and (Value[I] <= '9') then
      Part := Part + Value[I]
    else
      Exit;
  end;

  if Part = '' then Exit;
  Num := StrToIntDef(Part, -1);
  if (Num < 0) or (Num > 255) then Exit;

  Result := DotCount = 3;
end;

procedure InitializeWizard;
begin
  ServerIpPage := CreateInputQueryPage(
    wpSelectTasks,
    'Configuracion de servidor',
    'Direccion del servidor VIGIA',
    'Introduce la IP del equipo del profesor. Esta configuracion se guardara en ProgramData.'
  );
  ServerIpPage.Add('IP del servidor:', False);
  ServerIpPage.Values[0] := '192.168.1.2';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Ip: string;
begin
  Result := True;
  if CurPageID = ServerIpPage.ID then
  begin
    Ip := Trim(ServerIpPage.Values[0]);
    if not IsValidIPv4(Ip) then
    begin
      MsgBox('Introduce una direccion IPv4 valida (ejemplo: 192.168.1.2).', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigDir: string;
  ConfigFile: string;
  Ip: string;
begin
  if CurStep = ssPostInstall then
  begin
    Ip := Trim(ServerIpPage.Values[0]);
    ConfigDir := ExpandConstant('{commonappdata}\\VIGIA');
    if not DirExists(ConfigDir) then
      ForceDirectories(ConfigDir);

    ConfigFile := AddBackslash(ConfigDir) + 'client.conf';
    SaveStringToFile(ConfigFile, Ip + #13#10, False);
  end;
end;

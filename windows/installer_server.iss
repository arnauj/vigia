#define MyAppName "VIGIA Server"
#ifndef AppVersion
  #define AppVersion "1.1"
#endif
#ifndef SourceDir
  #define SourceDir "..\\dist\\windows\\bin\\VIGIA-Server"
#endif
#ifndef OutputDir
  #define OutputDir "..\\dist\\windows\\installers"
#endif

[Setup]
AppId={{487B508B-92F1-4632-8D6F-830D55495F6F}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher=VIGIA
DefaultDirName={autopf}\\VIGIA Server
DefaultGroupName={#MyAppName}
OutputDir={#OutputDir}
OutputBaseFilename=vigia-server-{#AppVersion}-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "autostart"; Description: "Iniciar VIGIA Server al arrancar Windows"; GroupDescription: "Inicio automático:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\\VIGIA Server"; Filename: "{app}\\VIGIA-Server.exe"
Name: "{commondesktop}\\VIGIA Server"; Filename: "{app}\\VIGIA-Server.exe"; Tasks: desktopicon
Name: "{commonstartup}\\VIGIA Server"; Filename: "{app}\\VIGIA-Server.exe"; Tasks: autostart

[Run]
Filename: "{app}\\VIGIA-Server.exe"; Description: "Iniciar VIGIA Server"; Flags: nowait postinstall skipifsilent

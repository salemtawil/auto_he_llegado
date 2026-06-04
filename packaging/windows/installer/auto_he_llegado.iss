#define MyAppName "Auto He Llegado"
#define MyAppExeName "AutoHeLlegado.exe"

#ifndef DistAppDir
  #error DistAppDir no definido. Usa build_installer_windows.ps1.
#endif

#ifndef OutputDir
  #error OutputDir no definido. Usa build_installer_windows.ps1.
#endif

#ifndef OutputBaseFilename
  #error OutputBaseFilename no definido. Usa build_installer_windows.ps1.
#endif

#ifndef AppVersion
  #define AppVersion "dev"
#endif

[Setup]
AppId={{77A85A45-5F07-4D7C-A5CC-7A4EBE1F70A9}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName}
DefaultDirName={localappdata}\Programs\AutoHeLlegado
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistAppDir}\AutoHeLlegado.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistAppDir}\AutoHeLlegadoUploader.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistAppDir}\AutoHeLlegadoDebugInspector.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistAppDir}\AutoHeLlegadoUpdateHelper.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistAppDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistAppDir}\updater\*"; DestDir: "{app}\updater"; Excludes: "updater_config.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistAppDir}\updater\updater_config.json"; DestDir: "{app}\updater"; Flags: ignoreversion
Source: "{#DistAppDir}\browser_extension\*"; DestDir: "{app}\browser_extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistAppDir}\ms-playwright\*"; DestDir: "{app}\ms-playwright"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistAppDir}\.env"; DestDir: "{app}"; DestName: ".env"; Flags: ignoreversion onlyifdoesntexist uninsneveruninstall
Source: "{#DistAppDir}\.env.example"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\logs"; Flags: uninsneveruninstall
Name: "{app}\exports"; Flags: uninsneveruninstall
Name: "{app}\updates"; Flags: uninsneveruninstall
Name: "{app}\updates\backups"; Flags: uninsneveruninstall
Name: "{app}\updates\update_logs"; Flags: uninsneveruninstall
Name: "{app}\updates\staging"; Flags: uninsneveruninstall
Name: "{app}\local_data"; Flags: uninsneveruninstall
Name: "{app}\local_data\config"; Flags: uninsneveruninstall
Name: "{app}\local_data\logs"; Flags: uninsneveruninstall
Name: "{app}\local_data\debug"; Flags: uninsneveruninstall
Name: "{app}\local_data\results"; Flags: uninsneveruninstall
Name: "{app}\local_data\results\screenshots"; Flags: uninsneveruninstall
Name: "{app}\local_data\failed_uploads"; Flags: uninsneveruninstall
Name: "{app}\local_data\temp_photos"; Flags: uninsneveruninstall
Name: "{app}\chrome_profiles"; Flags: uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\AutoHeLlegado.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\AutoHeLlegado.exe"; Tasks: desktopicon

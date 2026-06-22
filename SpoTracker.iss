[Setup]
AppId={{402327EE-B0CC-4F5E-B760-1E0860434DD0}}
AppName=SpoTracker
AppVersion=0.0.0
DefaultDirName={pf}\SpoTracker
DefaultGroupName=SpoTracker
OutputDir=output
OutputBaseFilename=SpoTrackerInstaller
Compression=lzma
SolidCompression=yes

[Files]
; Main tracker (onedir build)
Source: "dist\SpoTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
; Stats report generator (onefile build)
Source: "dist\SpoTracker-Stats.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu shortcuts
Name: "{group}\SpoTracker";            Filename: "{app}\SpoTracker.exe"
Name: "{group}\Open Report";           Filename: "{userdocs}\SpoTracker\reports\tracks-by-artist.html"
Name: "{group}\Generate New Report";   Filename: "{app}\SpoTracker-Stats.exe"
Name: "{group}\Uninstall";             Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "SpoTracker"; \
    ValueData: """{app}\SpoTracker.exe"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\SpoTracker.exe"; Flags: nowait postinstall skipifsilent; \
    Description: "Start SpoTracker"
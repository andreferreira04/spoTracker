[Setup]
AppId={{402327EE-B0CC-4F5E-B760-1E0860434DD0}}
AppName=SpoTracker
AppVersion=1.0
DefaultDirName={pf}\SpoTracker
DefaultGroupName=SpoTracker
OutputDir=output
OutputBaseFilename=SpoTrackerInstaller
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\SpoTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "SpoTracker"; \
    ValueData: """{app}\SpoTracker.exe"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\SpoTracker.exe"; Flags: nowait postinstall
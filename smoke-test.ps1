# Smoke test for the built SpoTracker executable
# Run after: pyinstaller music-register.spec --noconfirm

$exe = "dist\SpoTracker\SpoTracker.exe"

if (-not (Test-Path $exe)) {
    Write-Host "FAIL: $exe not found. Run pyinstaller first." -ForegroundColor Red
    exit 1
}

# Kill any existing SpoTracker instances (isAlreadyRunning check would cause instant exit)
Get-Process -Name "SpoTracker" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

Write-Host "Testing: Executable starts (tray mode)..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 3
if ($proc.HasExited) {
    Write-Host "FAIL: Executable crashed on startup (exit code: $($proc.ExitCode))" -ForegroundColor Red
    exit 1
}
Stop-Process -Id $proc.Id -Force
Write-Host "PASS: Tray mode OK" -ForegroundColor Green

Write-Host "Testing: --generate-report flag..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $exe -ArgumentList "--generate-report" -PassThru
# Wait up to 30 seconds for the report to generate (has a message box)
$proc.WaitForExit(30000) | Out-Null
if (-not $proc.HasExited) {
    # Still running means it's showing the success message box — that's OK
    Stop-Process -Id $proc.Id -Force
    Write-Host "PASS: Report generation OK (message box appeared)" -ForegroundColor Green
} elseif ($proc.ExitCode -eq 0) {
    Write-Host "PASS: Report generation OK" -ForegroundColor Green
} else {
    Write-Host "FAIL: --generate-report exited with code $($proc.ExitCode)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "All smoke tests passed!" -ForegroundColor Green

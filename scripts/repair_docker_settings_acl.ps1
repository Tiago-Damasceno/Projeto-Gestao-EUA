$ErrorActionPreference = 'Stop'

$dockerDirectory = [IO.Path]::GetFullPath(
    (Join-Path $env:APPDATA 'Docker')
)
$expectedDirectory = [IO.Path]::GetFullPath(
    (Join-Path $env:USERPROFILE 'AppData\Roaming\Docker')
)

if ($dockerDirectory -ne $expectedDirectory) {
    throw 'Unexpected Docker settings path.'
}
if (-not (Test-Path -LiteralPath $dockerDirectory -PathType Container)) {
    throw 'Docker settings directory does not exist.'
}

$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$grant = $account + ':(OI)(CI)F'
& icacls.exe $dockerDirectory /grant:r $grant /T /C | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'icacls failed to repair the Docker settings directory.'
}

$probe = Join-Path $dockerDirectory 'codex-permission-probe.tmp'
$renamedProbe = Join-Path $dockerDirectory 'codex-permission-probe.ok'
Remove-Item -LiteralPath $probe, $renamedProbe -Force -ErrorAction SilentlyContinue
Set-Content -LiteralPath $probe -Value 'probe' -NoNewline
Move-Item -LiteralPath $probe -Destination $renamedProbe
Remove-Item -LiteralPath $renamedProbe -Force

$statusFile = Join-Path $env:TEMP 'codex-docker-acl-repair.status'
Set-Content -LiteralPath $statusFile -Value (
    'success|' + $account + '|' + (Get-Date).ToString('o')
) -NoNewline

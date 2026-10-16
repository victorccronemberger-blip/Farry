param(
    [Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$SourceVersion,
    [Parameter(Mandatory=$true)][string]$IsccPath,
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [switch]$Resume
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$source = Join-Path $repo 'dist'
$directory = Join-Path $repo ('dist\releases\' + $Version)
$work = Join-Path $repo ('work\distribution-' + $Version)
$package = Join-Path $work 'app'
if ((Test-Path -LiteralPath $directory) -and -not $Resume) { throw 'Diretório desta release já existe; não será sobrescrito.' }
if ((Test-Path -LiteralPath $work) -and -not $Resume) { throw 'Diretório de trabalho desta release já existe; preserve-o para inspeção.' }
& node "$PSScriptRoot\check-release.mjs" $SourceVersion $source
if ($LASTEXITCODE -ne 0) { throw 'A distribuição-base não foi autenticada.' }
$manifest = Get-Content -LiteralPath (Join-Path $source 'release.json') -Raw | ConvertFrom-Json
$applicationVersion = if ($manifest.application_version) { $manifest.application_version } else { $manifest.version }
New-Item -ItemType Directory -Force -Path $directory,$package | Out-Null
$sourceCheckpoint = Join-Path $work 'source-package.sha256'
if ($Resume -and ((-not (Test-Path -LiteralPath $sourceCheckpoint)) -or
    (Get-Content -LiteralPath $sourceCheckpoint -Raw).Trim() -ne $manifest.package.sha256)) {
    throw 'Checkpoint da distribuição-base ausente ou divergente. Retomada recusada.'
}
$extractor = @'
import pathlib,stat,sys,zipfile
root=pathlib.Path(sys.argv[2]).resolve()
with zipfile.ZipFile(sys.argv[1]) as archive:
    seen=set()
    for item in archive.infolist():
        target=(root/item.filename).resolve()
        key=str(target).casefold()
        if not target.is_relative_to(root) or key in seen or stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError('Unsafe package entry')
        seen.add(key)
    archive.extractall(root)
'@
if (-not $Resume) {
    & $python -c $extractor (Join-Path $source 'Farry-windows-x64.zip') $package
    if ($LASTEXITCODE -ne 0) { throw 'Extração da distribuição-base falhou.' }
    $manifest.package.sha256 | Set-Content -LiteralPath $sourceCheckpoint -Encoding ASCII
}
foreach ($binary in @('QMoney.exe', 'QMoneyUpdater.exe', 'runtime\QMoneyService.exe')) {
    & "$PSScriptRoot\sign-internal.ps1" -Path (Join-Path $package $binary)
}
$previousVersion = $env:QMONEY_VERSION
$env:QMONEY_VERSION = $applicationVersion
try {
    & $python "$ProjectRoot\scripts\verify_packaged_service.py" "$package\runtime\QMoneyService.exe" --report "$work\service-validation.json" --request-timeout 45
} finally { $env:QMONEY_VERSION = $previousVersion }
if ($LASTEXITCODE -ne 0) { throw 'Validação isolada do motor falhou. A release não será assinada/publicada.' }
$provenance = [ordered]@{
    source_release = 'v' + $SourceVersion
    source_package_sha256 = $manifest.package.sha256
    application_version = $applicationVersion
    runtime_code_changes = $false
    distribution_changes = @('per-user installer', 'registered uninstaller', 'internal Authenticode', 'release verification')
}
$provenance | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $directory 'payload-source.json') -Encoding UTF8
& "$PSScriptRoot\build-launcher.ps1" -Version $Version -IsccPath $IsccPath -OutputDirectory $directory -InternalSigning
& "$PSScriptRoot\test-internal-signing.ps1" -ArtifactDirectory $directory
$zipper = @'
import pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1])
with zipfile.ZipFile(sys.argv[2], 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(root.rglob('*')):
        if path.is_file(): archive.write(path, path.relative_to(root).as_posix())
'@
& $python -c $zipper $package (Join-Path $directory 'Farry-windows-x64.zip')
if ($LASTEXITCODE -ne 0) { throw 'Compressão da distribuição falhou.' }
& node "$PSScriptRoot\sign-release.mjs" $Version $directory $applicationVersion
if ($LASTEXITCODE -ne 0) { throw 'Assinatura do manifesto falhou.' }
& node "$PSScriptRoot\check-release.mjs" $Version $directory
if ($LASTEXITCODE -ne 0) { throw 'Verificação final dos artefatos falhou.' }
Write-Output "Distribuição autenticada e validada: $directory"

param([Parameter(Mandatory=$true)][string]$ProjectRoot, [switch]$InternalSigning = $true)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$work = Join-Path $repo ('work\package-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$package = Join-Path $work 'app'
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$gui = Join-Path $ProjectRoot 'dist-local\QMoney.exe'
if (-not (Test-Path -LiteralPath $gui)) { throw 'Distribuição testada não encontrada.' }
$version = (Get-Item -LiteralPath $gui).VersionInfo.ProductVersion
if (-not $version) {
    $match = [regex]::Match((Get-Content -LiteralPath "$ProjectRoot\desktop\CMakeLists.txt" -Raw), 'set\(QMONEY_VERSION "([0-9]+\.[0-9]+\.[0-9]+)"\)')
    if ($match.Success) { $version = $match.Groups[1].Value }
}
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Versão do aplicativo inválida.' }
New-Item -ItemType Directory -Force -Path $package,(Join-Path $work 'spec') | Out-Null
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $repo 'work\build-dependencies'
try {
    & $python -m PyInstaller --noconfirm --onedir --windowed --name QMoneyService `
        --paths $ProjectRoot --icon "$ProjectRoot\desktop\resources\qmoney.ico" `
        --distpath "$work\service" --workpath "$work\pyinstaller" --specpath "$work\spec" `
        --collect-data moneymin --collect-submodules moneymin --collect-all curl_cffi --collect-all ijson `
        --collect-submodules playwright --collect-submodules boto3 --collect-submodules ego4d `
        --collect-all projectaria_tools --hidden-import _core_pybinds --hidden-import _adt_pybinds `
        --hidden-import _aea_pybinds --hidden-import _ase_pybinds `
        --add-data "$ProjectRoot\moneymin\resources;moneymin/resources" `
        --add-data "$ProjectRoot\reference;reference" "$ProjectRoot\packaging\qmoney_service.py"
    if ($LASTEXITCODE -ne 0) { throw 'Empacotamento do motor falhou.' }
} finally { $env:PYTHONPATH = $previousPythonPath }
foreach ($item in (Get-ChildItem -LiteralPath "$ProjectRoot\dist-local")) {
    if ($item.Name -match '\.(previous|next)\.exe$' -or $item.Name -eq 'runtime') { continue }
    Copy-Item -LiteralPath $item.FullName -Destination $package -Recurse
}
Copy-Item -LiteralPath "$work\service\QMoneyService" -Destination "$package\runtime" -Recurse
New-Item -ItemType Directory -Force -Path "$package\runtime\tools\ffmpeg\bin" | Out-Null
foreach ($name in @('ffmpeg.exe','ffprobe.exe')) {
    $binary = Get-ChildItem -LiteralPath "$ProjectRoot\tools\ffmpeg" -Recurse -File -Filter $name | Select-Object -First 1
    if (-not $binary) { throw "Ferramenta ausente: $name" }
    Copy-Item -LiteralPath $binary.FullName -Destination "$package\runtime\tools\ffmpeg\bin"
}
. "$ProjectRoot\scripts\browser_parts.ps1"
$manifest = & $python -c 'import pathlib,playwright; print(pathlib.Path(playwright.__file__).parent / "driver/package/browsers.json")'
if ($LASTEXITCODE -ne 0) { throw 'Playwright ausente.' }
New-Item -ItemType Directory -Force -Path "$package\runtime\ms-playwright" | Out-Null
foreach ($part in (Get-QMoneyBrowserParts -ManifestPath $manifest -BrowserSource "$ProjectRoot\tools\ms-playwright")) {
    Copy-Item -LiteralPath $part.FullName -Destination "$package\runtime\ms-playwright" -Recurse
}
& $python "$ProjectRoot\scripts\verify_packaged_service.py" "$package\runtime\QMoneyService.exe" --report "$work\service-validation.json"
if ($LASTEXITCODE -ne 0) { throw 'Motor empacotado não passou na validação isolada.' }
if ($InternalSigning) {
    foreach ($binary in @('QMoney.exe', 'QMoneyUpdater.exe', 'runtime\QMoneyService.exe')) {
        & "$PSScriptRoot\sign-internal.ps1" -Path (Join-Path $package $binary)
    }
}
New-Item -ItemType Directory -Force -Path "$repo\dist" | Out-Null
& $python -c 'import sys,zipfile,pathlib; root=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2],"w",zipfile.ZIP_DEFLATED,compresslevel=6); [z.write(p,p.relative_to(root).as_posix()) for p in root.rglob("*") if p.is_file()]; z.close()' $package "$repo\dist\Farry-windows-x64.zip"
if ($LASTEXITCODE -ne 0) { throw 'Compressão falhou.' }
& node "$repo\tools\sign-release.mjs" $version
if ($LASTEXITCODE -ne 0) { throw 'Assinatura falhou.' }
Write-Output "Pacote $version preparado em $repo\dist"

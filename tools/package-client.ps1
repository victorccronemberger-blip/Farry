param(
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [Parameter(Mandatory=$true)][string]$BuildDirectory,
    [Parameter(Mandatory=$true)][string]$QtRoot,
    [Parameter(Mandatory=$true)][ValidatePattern('^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$')][string]$Version,
    [string]$CompilerBinDirectory,
    [string]$UcrtDirectory,
    [string]$OutputDirectory,
    [switch]$InternalSigning = $true
)
$ErrorActionPreference = 'Stop'

function Resolve-RequiredDirectory([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label não encontrado: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

$ProjectRoot = Resolve-RequiredDirectory $ProjectRoot 'Raiz do projeto'
$BuildDirectory = Resolve-RequiredDirectory $BuildDirectory 'Diretório do build compilado'
$QtRoot = Resolve-RequiredDirectory $QtRoot 'QtRoot'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$gui = Join-Path $BuildDirectory 'QMoney.exe'
$updater = Join-Path $BuildDirectory 'QMoneyUpdater.exe'
$windeployqt = Join-Path $QtRoot 'bin\windeployqt.exe'
$ffmpegRoot = Join-Path $ProjectRoot 'tools\ffmpeg'
$browserRoot = Join-Path $ProjectRoot 'tools\ms-playwright'
$browserPartsScript = Join-Path $ProjectRoot 'scripts\browser_parts.ps1'
$verifyScript = Join-Path $ProjectRoot 'scripts\verify_packaged_service.py'
$signScript = Join-Path $PSScriptRoot 'sign-internal.ps1'
$releaseSigner = Join-Path $PSScriptRoot 'sign-release.mjs'
$dependencyRoot = Join-Path $repo 'work\build-dependencies'

foreach ($requiredFile in @(
    $python, $gui, $updater, $windeployqt,
    (Join-Path $ProjectRoot 'packaging\qmoney_service.py'),
    (Join-Path $ProjectRoot 'desktop\resources\qmoney.ico'),
    (Join-Path $ProjectRoot 'moneymin\samsung_uw_calibration.json'),
    (Join-Path $ProjectRoot 'moneymin\minute_task_names.json'),
    $verifyScript, $browserPartsScript, $signScript, $releaseSigner,
    (Join-Path $repo 'app.js'), (Join-Path $repo 'secrets\update-private.pem'),
    (Join-Path $PSScriptRoot 'check-release.mjs')
)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) { throw "Arquivo necessário ausente: $requiredFile" }
}
$exeVersion = ([string](Get-Item -LiteralPath $gui).VersionInfo.ProductVersion).Trim()
if ($exeVersion -ne $Version) {
    throw "Versão do executável compilado ($exeVersion) difere da versão solicitada ($Version)."
}
if (-not (Test-Path -LiteralPath $dependencyRoot -PathType Container)) {
    throw "Dependências PyInstaller ausentes: $dependencyRoot"
}
if (-not (Test-Path -LiteralPath $ffmpegRoot -PathType Container)) { throw "FFmpeg ausente: $ffmpegRoot" }
if (-not (Test-Path -LiteralPath $browserRoot -PathType Container)) { throw "Navegadores Playwright ausentes: $browserRoot" }
$output = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else {
    Join-Path $repo ('dist\releases\' + $Version)
}
$installer = Join-Path $output 'FarrySetup.exe'
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Instalador Farry da versão $Version precisa estar pronto no diretório de saída: $installer"
}
$installerVersion = ([string](Get-Item -LiteralPath $installer).VersionInfo.ProductVersion).Trim()
if ($installerVersion -ne $Version) {
    throw "Versão do instalador ($installerVersion) difere da versão solicitada ($Version)."
}
if (-not (Get-Command 'node.exe' -ErrorAction SilentlyContinue)) { throw 'Node.js não encontrado no PATH.' }

$compilerBin = if ($CompilerBinDirectory) {
    Resolve-RequiredDirectory $CompilerBinDirectory 'Diretório do compilador MinGW'
} else {
    $compiler = Get-Command 'g++.exe' -ErrorAction SilentlyContinue
    if (-not $compiler) { throw 'MinGW ausente no PATH. Informe -CompilerBinDirectory com o diretório bin do compilador.' }
    Split-Path -Parent $compiler.Source
}
$compilerRuntimes = @('libstdc++-6.dll', 'libgcc_s_seh-1.dll', 'libwinpthread-1.dll')
foreach ($runtimeName in $compilerRuntimes) {
    if (-not (Test-Path -LiteralPath (Join-Path $compilerBin $runtimeName) -PathType Leaf)) {
        throw "Runtime MinGW ausente em ${compilerBin}: $runtimeName"
    }
}

$ffmpeg = Get-ChildItem -LiteralPath $ffmpegRoot -Recurse -File -Filter 'ffmpeg.exe' | Select-Object -First 1
$ffprobe = Get-ChildItem -LiteralPath $ffmpegRoot -Recurse -File -Filter 'ffprobe.exe' | Select-Object -First 1
if (-not $ffmpeg -or -not $ffprobe) { throw 'FFmpeg/FFprobe não encontrados no diretório de ferramentas.' }

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $dependencyRoot
try {
    & $python -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller não está disponível no ambiente configurado.' }
    $browserManifest = & $python -c 'import pathlib,playwright; print(pathlib.Path(playwright.__file__).parent / "driver/package/browsers.json")'
    if ($LASTEXITCODE -ne 0) { throw 'Playwright ausente no ambiente Python.' }
} finally { $env:PYTHONPATH = $previousPythonPath }
if (-not (Test-Path -LiteralPath $browserManifest -PathType Leaf)) { throw "Manifesto Playwright ausente: $browserManifest" }
. $browserPartsScript
$browserParts = @(Get-QMoneyBrowserParts -ManifestPath $browserManifest -BrowserSource $browserRoot)
if ($browserParts.Count -ne 4) { throw 'O conjunto de navegadores Playwright está incompleto.' }

$ucrtSearchRoot = if ($UcrtDirectory) {
    Resolve-RequiredDirectory $UcrtDirectory 'Diretório de redistribuição do UCRT'
} else {
    Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Redist'
}
if (-not (Test-Path -LiteralPath $ucrtSearchRoot -PathType Container)) {
    throw "Redistribuíveis do Windows SDK ausentes: $ucrtSearchRoot. Informe -UcrtDirectory para um SDK local."
}
$ucrtBase = Get-ChildItem -LiteralPath $ucrtSearchRoot -Recurse -File -Filter 'ucrtbase.dll' -ErrorAction SilentlyContinue |
    Where-Object FullName -Match '\\ucrt\\DLLs\\x64\\ucrtbase\.dll$' |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $ucrtBase) { throw 'UCRT x64 de redistribuição não encontrado no Windows SDK.' }

$work = Join-Path $repo ('work\package-' + $Version)
if (Test-Path -LiteralPath $work) { throw "Diretório de trabalho já existe; preserve-o para inspeção: $work" }
$packageZip = Join-Path $output 'Farry-windows-x64.zip'
foreach ($artifact in @($packageZip, (Join-Path $output 'release.json'), (Join-Path $output 'release.json.sig'))) {
    if (Test-Path -LiteralPath $artifact) { throw "Artefato de saída já existe; não será sobrescrito: $artifact" }
}
New-Item -ItemType Directory -Force -Path $output | Out-Null
$package = Join-Path $work 'app'
New-Item -ItemType Directory -Force -Path $package,(Join-Path $work 'spec') | Out-Null

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $dependencyRoot
try {
    & $python -m PyInstaller --noconfirm --onedir --windowed --name QMoneyService `
        --paths $ProjectRoot --icon (Join-Path $ProjectRoot 'desktop\resources\qmoney.ico') `
        --distpath (Join-Path $work 'service') --workpath (Join-Path $work 'pyinstaller') `
        --specpath (Join-Path $work 'spec') `
        --collect-data moneymin --collect-submodules moneymin --collect-all curl_cffi --collect-all ijson `
        --collect-submodules playwright --collect-submodules boto3 --collect-submodules ego4d `
        --collect-all projectaria_tools --hidden-import _core_pybinds --hidden-import _adt_pybinds `
        --hidden-import _aea_pybinds --hidden-import _ase_pybinds `
        --add-data (Join-Path $ProjectRoot 'moneymin\samsung_uw_calibration.json;moneymin') `
        --add-data (Join-Path $ProjectRoot 'moneymin\minute_task_names.json;moneymin') `
        --add-data (Join-Path $ProjectRoot 'moneymin\resources;moneymin/resources') `
        --add-data (Join-Path $ProjectRoot 'reference;reference') `
        (Join-Path $ProjectRoot 'packaging\qmoney_service.py')
    if ($LASTEXITCODE -ne 0) { throw 'Empacotamento do motor PyInstaller falhou.' }
} finally { $env:PYTHONPATH = $previousPythonPath }

Copy-Item -LiteralPath $gui -Destination (Join-Path $package 'QMoney.exe')
Copy-Item -LiteralPath $updater -Destination (Join-Path $package 'QMoneyUpdater.exe')
$previousPath = $env:PATH
try {
    $env:PATH = "$compilerBin;$previousPath"
    & $windeployqt --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime (Join-Path $package 'QMoney.exe')
    if ($LASTEXITCODE -ne 0) { throw 'windeployqt falhou; distribuição Qt incompleta.' }
} finally { $env:PATH = $previousPath }
foreach ($runtimeName in $compilerRuntimes) {
    $deployedRuntime = Get-ChildItem -LiteralPath $package -Recurse -File -Filter $runtimeName | Select-Object -First 1
    if (-not $deployedRuntime) { throw "windeployqt não incluiu o runtime MinGW exigido: $runtimeName" }
}

$runtime = Join-Path $package 'runtime'
$service = Join-Path $work 'service\QMoneyService'
if (-not (Test-Path -LiteralPath $service -PathType Container)) { throw 'PyInstaller não criou QMoneyService.' }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
Get-ChildItem -LiteralPath $service | Copy-Item -Destination $runtime -Recurse
$mediaBin = Join-Path $runtime 'tools\ffmpeg\bin'
New-Item -ItemType Directory -Force -Path $mediaBin | Out-Null
Copy-Item -LiteralPath $ffmpeg.FullName -Destination $mediaBin
Copy-Item -LiteralPath $ffprobe.FullName -Destination $mediaBin
Get-ChildItem -LiteralPath $ucrtBase.Directory.FullName -File -Filter '*.dll' |
    Copy-Item -Destination $mediaBin

$browserTarget = Join-Path $runtime 'ms-playwright'
New-Item -ItemType Directory -Force -Path $browserTarget | Out-Null
foreach ($part in $browserParts) {
    Copy-Item -LiteralPath $part.FullName -Destination $browserTarget -Recurse
}

$validationReport = Join-Path $work 'service-validation.json'
& $python $verifyScript (Join-Path $runtime 'QMoneyService.exe') --report $validationReport --request-timeout 45
if ($LASTEXITCODE -ne 0) { throw 'Motor empacotado não passou na validação isolada.' }

if ($InternalSigning) {
    foreach ($relativePath in @('QMoney.exe', 'QMoneyUpdater.exe', 'runtime\QMoneyService.exe')) {
        & $signScript -Path (Join-Path $package $relativePath)
    }
}

$zipper = @'
import pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1])
with zipfile.ZipFile(sys.argv[2], 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
for path in sorted(root.rglob('*')):
    if path.is_file(): archive.write(path, path.relative_to(root).as_posix())
'@
& $python -c $zipper $package $packageZip
if ($LASTEXITCODE -ne 0) { throw 'Compressão da distribuição Farry falhou.' }
& node $releaseSigner $Version $output $Version
if ($LASTEXITCODE -ne 0) { throw 'Assinatura do manifesto da release falhou.' }
& node (Join-Path $PSScriptRoot 'check-release.mjs') $Version $output
if ($LASTEXITCODE -ne 0) { throw 'Verificação dos artefatos da release falhou.' }
Write-Output "Pacote $Version preparado em $output"

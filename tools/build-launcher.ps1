param(
    [Parameter(Mandatory=$true)][ValidatePattern('^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$')][string]$Version,
    [string]$IsccPath,
    [string]$OutputDirectory,
    [switch]$InternalSigning = $true
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework 4.x não encontrado.' }
$output = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $repo 'work\installer-candidate' }
if (-not $IsccPath) { $IsccPath = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
if (-not $IsccPath) { $IsccPath = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
if (-not (Test-Path -LiteralPath $IsccPath -PathType Leaf)) {
    throw 'Compilador Inno Setup ausente. Informe -IsccPath. Nenhum instalador foi gerado.'
}
New-Item -ItemType Directory -Force -Path $output | Out-Null
$assemblyInfo = Join-Path $output 'AssemblyInfo.cs'
@"
[assembly: System.Reflection.AssemblyTitle("Farry - QMoney")]
[assembly: System.Reflection.AssemblyDescription("Instalar, abrir e atualizar QMoney")]
[assembly: System.Reflection.AssemblyCompany("Farry")]
[assembly: System.Reflection.AssemblyProduct("Farry")]
[assembly: System.Reflection.AssemblyVersion("$Version.0")]
[assembly: System.Reflection.AssemblyFileVersion("$Version.0")]
"@ | Set-Content -LiteralPath $assemblyInfo -Encoding UTF8
& $compiler /nologo /target:winexe /optimize+ /platform:x64 "/out:$output\FarryLauncher.exe" `
    "/win32icon:$repo\client\desktop\resources\qmoney.ico" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Net.Http.dll `
    /r:System.Web.Extensions.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll `
    /r:Microsoft.CSharp.dll "$repo\launcher\Launcher.cs" "$repo\launcher\ReleasePolicy.cs" "$repo\launcher\ReleaseKey.cs" `
    "$repo\launcher\ReleaseActivation.cs" $assemblyInfo
if ($LASTEXITCODE -ne 0) { throw 'Compilação do launcher falhou.' }
$signingOptions = @()
if ($InternalSigning) {
    & "$PSScriptRoot\sign-internal.ps1" -Path "$output\FarryLauncher.exe"
    $signer = Join-Path $PSScriptRoot 'sign-internal.ps1'
    $signingShell = (Get-Process -Id $PID).Path
    $signCommand = 'farry=$q' + $signingShell + '$q -NoProfile -NonInteractive -File $q' + $signer + '$q -Path $f'
    $signingOptions = @('/DInternalSigning=1', ('/S' + $signCommand))
}
& $IsccPath "/DLauncherVersion=$Version" "/DArtifactDir=$output" @signingOptions "$repo\installer\Farry.iss"
if ($LASTEXITCODE -ne 0) { throw 'Compilação do instalador falhou.' }
Write-Output "Launcher e instalador: $output"

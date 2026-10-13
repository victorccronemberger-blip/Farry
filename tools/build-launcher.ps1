$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework 4.x não encontrado.' }
$output = Join-Path $repo 'dist'
New-Item -ItemType Directory -Force -Path $output | Out-Null
& $compiler /nologo /target:winexe /optimize+ /platform:x64 "/out:$output\FarryLauncher.exe" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Net.Http.dll `
    /r:System.Web.Extensions.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll `
    /r:Microsoft.CSharp.dll "$repo\launcher\Launcher.cs" "$repo\launcher\ReleasePolicy.cs" "$repo\launcher\ReleaseKey.cs"
if ($LASTEXITCODE -ne 0) { throw 'Compilação do launcher falhou.' }
Copy-Item -LiteralPath "$output\FarryLauncher.exe" -Destination "$output\FarrySetup.exe" -Force
Write-Output "Launcher e instalador: $output"

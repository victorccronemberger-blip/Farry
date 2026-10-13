$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$output = Join-Path $repo 'work\launcher-tests'
New-Item -ItemType Directory -Force -Path $output | Out-Null
& node "$repo\tools\test-signature-fixture.mjs"
if ($LASTEXITCODE -ne 0) { throw 'Fixture de assinatura falhou.' }
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:exe /main:LauncherTests /platform:x64 "/out:$output\tests.exe" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Net.Http.dll /r:System.Web.Extensions.dll `
    /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll /r:Microsoft.CSharp.dll `
    "$repo\launcher\ReleasePolicy.cs" "$repo\launcher\ReleaseKey.cs" "$repo\test\LauncherTests.cs"
if ($LASTEXITCODE -ne 0) { throw 'Compilação de testes falhou.' }
& "$output\tests.exe" "$output\valid.json" "$output\invalid.json"
if ($LASTEXITCODE -ne 0) { throw 'Teste de launcher falhou.' }

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$output = Join-Path $repo ('work\launcher-tests\' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $output | Out-Null
& node "$repo\tools\test-signature-fixture.mjs" $output
if ($LASTEXITCODE -ne 0) { throw 'Fixture de assinatura falhou.' }
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:exe /main:LauncherTests /platform:x64 "/out:$output\tests.exe" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Net.Http.dll /r:System.Web.Extensions.dll `
    /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll /r:Microsoft.CSharp.dll `
    "$repo\launcher\ReleasePolicy.cs" "$repo\launcher\ReleaseKey.cs" "$repo\test\LauncherTests.cs"
if ($LASTEXITCODE -ne 0) { throw 'Compilação de testes falhou.' }
& "$PSScriptRoot\sign-internal.ps1" -Path "$output\tests.exe"
& "$output\tests.exe" "$output\valid.json" "$output\invalid.json"
if ($LASTEXITCODE -ne 0) { throw 'Teste de launcher falhou.' }
& $compiler /nologo /target:exe /main:ActivationTests /platform:x64 "/out:$output\ActivationTests.exe" `
    /r:System.Net.Http.dll /r:System.Web.Extensions.dll `
    /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll `
    "$repo\launcher\ReleaseActivation.cs" "$repo\launcher\ReleasePolicy.cs" "$repo\launcher\ReleaseKey.cs" "$repo\test\ActivationTests.cs"
if ($LASTEXITCODE -ne 0) { throw 'Compilação dos testes de ativação falhou.' }
& "$PSScriptRoot\sign-internal.ps1" -Path "$output\ActivationTests.exe"
& "$output\ActivationTests.exe"
if ($LASTEXITCODE -ne 0) { throw 'Teste de ativação falhou.' }

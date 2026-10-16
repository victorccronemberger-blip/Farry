param([Parameter(Mandatory=$true)][string]$ArtifactDirectory)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$publicPath = if ($env:FARRY_INTERNAL_CERTIFICATE) { $env:FARRY_INTERNAL_CERTIFICATE } else { Join-Path $repo 'keys\internal-codesigning.cer' }
$public = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($publicPath)
foreach ($name in @('FarryLauncher.exe', 'FarrySetup.exe')) {
    $file = Join-Path $ArtifactDirectory $name
    & "$PSScriptRoot\verify-internal-signature.ps1" -Path $file
    $signature = Get-AuthenticodeSignature -LiteralPath $file
    if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $public.Thumbprint -or
        $signature.Status -eq 'HashMismatch' -or $signature.Status -eq 'NotSigned') {
        throw "Identidade interna ausente ou assinatura danificada: $name"
    }
}
$temporaryFile = Join-Path ([IO.Path]::GetTempPath()) ('FarryTamper-' + [guid]::NewGuid().ToString('N') + '.exe')
try {
    $bytes = [IO.File]::ReadAllBytes((Join-Path $ArtifactDirectory 'FarrySetup.exe'))
    $bytes[512] = $bytes[512] -bxor 1
    [IO.File]::WriteAllBytes($temporaryFile, $bytes)
    if ((Get-AuthenticodeSignature -LiteralPath $temporaryFile).Status -ne 'HashMismatch') {
        throw 'Adulteração não detectada pelo verificador Authenticode.'
    }
} finally {
    if (Test-Path -LiteralPath $temporaryFile) { Remove-Item -LiteralPath $temporaryFile -Force }
}
Write-Output 'Assinaturas internas conferidas; adulteração detectada. Nenhum executável foi iniciado.'

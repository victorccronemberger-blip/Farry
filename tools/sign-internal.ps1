param(
    [string]$Path,
    [switch]$Initialize
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$publicPath = if ($env:FARRY_INTERNAL_CERTIFICATE) { $env:FARRY_INTERNAL_CERTIFICATE } else { Join-Path $repo 'keys\internal-codesigning.cer' }
if (-not (Test-Path -LiteralPath $publicPath)) {
    if (-not $Initialize) { throw 'Inicialize a identidade interna com tools/sign-internal.ps1 -Initialize.' }
    $certificate = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=Farry Internal Code Signing' `
        -FriendlyName 'Farry - assinatura interna' -CertStoreLocation 'Cert:\CurrentUser\My' `
        -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears(5)
    Export-Certificate -Cert $certificate -FilePath $publicPath | Out-Null
} else {
    $public = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($publicPath)
    $certificate = Get-Item -LiteralPath ('Cert:\CurrentUser\My\' + $public.Thumbprint) -ErrorAction SilentlyContinue
    if (-not $certificate -or -not $certificate.HasPrivateKey) {
        throw 'Chave privada da identidade interna indisponível neste usuário. A identidade não será recriada.'
    }
}
if ($certificate.NotAfter -le (Get-Date)) { throw 'Certificado interno expirado. Planeje a renovação da identidade.' }
if ($Path) {
    $file = (Resolve-Path -LiteralPath $Path).Path
    $inputStream = [IO.File]::OpenRead($file)
    try {
        if ($inputStream.ReadByte() -ne 77 -or $inputStream.ReadByte() -ne 90) {
            throw 'Assinatura interna limitada a binários Windows PE.'
        }
    } finally { $inputStream.Dispose() }
    $result = Set-AuthenticodeSignature -LiteralPath $file -Certificate $certificate -HashAlgorithm SHA256 -IncludeChain Signer
    if (-not $result.SignerCertificate -or $result.SignerCertificate.Thumbprint -ne $certificate.Thumbprint -or
        $result.Status -eq 'HashMismatch' -or $result.Status -eq 'NotSigned') {
        throw "Assinatura interna não foi gravada: $($result.StatusMessage)"
    }
    & "$PSScriptRoot\verify-internal-signature.ps1" -Path $file
    Write-Output "Assinado internamente: $([IO.Path]::GetFileName($file)). Confiança do Windows: $($result.Status)."
} else {
    Write-Output "Identidade interna preparada: $($certificate.Thumbprint). Chave privada não exportável no perfil Windows."
}
# Intentionally never imports certificates into Root or TrustedPublisher.
# Internal Authenticode does not confer public Windows/SmartScreen trust.

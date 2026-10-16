param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$publicPath = if ($env:FARRY_INTERNAL_CERTIFICATE) { $env:FARRY_INTERNAL_CERTIFICATE } else { Join-Path $repo 'keys\internal-codesigning.cer' }
$public = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($publicPath)
$file = (Resolve-Path -LiteralPath $Path).Path
$signature = Get-AuthenticodeSignature -LiteralPath $file
if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $public.Thumbprint) {
    throw 'Assinatura da identidade interna esperada ausente.'
}
if (-not ('Farry.InternalTrust' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace Farry {
    public static class InternalTrust {
        [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
        struct FileInfo { public uint size; [MarshalAs(UnmanagedType.LPWStr)] public string path; public IntPtr handle, subject; }
        [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
        struct TrustData {
            public uint size; public IntPtr policy, sip; public uint ui, revocation, choice;
            public IntPtr file; public uint action; public IntPtr state, url; public uint flags, context; public IntPtr signatureSettings;
        }
        [DllImport("wintrust.dll", ExactSpelling=true, CharSet=CharSet.Unicode)]
        static extern int WinVerifyTrust(IntPtr window, ref Guid action, ref TrustData data);
        public static uint Verify(string path) {
            var file = new FileInfo { size=(uint)Marshal.SizeOf(typeof(FileInfo)), path=path };
            var pointer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(FileInfo)));
            Marshal.StructureToPtr(file, pointer, false);
            try {
                var data = new TrustData { size=(uint)Marshal.SizeOf(typeof(TrustData)), ui=2, choice=1, file=pointer, flags=0x1000 };
                var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");
                return unchecked((uint)WinVerifyTrust(new IntPtr(-1), ref action, ref data));
            } finally { Marshal.DestroyStructure(pointer, typeof(FileInfo)); Marshal.FreeHGlobal(pointer); }
        }
    }
}
'@
}
$result = [Farry.InternalTrust]::Verify($file)
# Only waive the expected untrusted self-signed root, never a generic trust error.
if ($result -ne 0 -and $result -ne 0x800B0109L) {
    throw ('Assinatura interna inválida: WinVerifyTrust 0x{0:X8}' -f $result)
}
Write-Output ('Assinatura interna íntegra: {0}; WinVerifyTrust=0x{1:X8}' -f [IO.Path]::GetFileName($file), $result)

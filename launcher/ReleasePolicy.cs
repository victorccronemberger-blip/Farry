using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class ReleasePolicy {
    internal const string Origin = "https://lightcyan-wolf-956118.hostingersite.com";
    internal static readonly Regex VersionPattern = new Regex(@"^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$");
    internal static Manifest Decode(string envelope) {
        var json = new JavaScriptSerializer { MaxJsonLength = 65536 };
        var signed = json.Deserialize<Envelope>(envelope);
        byte[] bytes = Convert.FromBase64String(signed.manifest), signature = Convert.FromBase64String(signed.signature);
        if (bytes.Length > 32768) throw new InvalidDataException("Manifesto excessivo.");
        using (var rsa = new RSACryptoServiceProvider()) {
            rsa.PersistKeyInCsp = false; rsa.FromXmlString(ReleaseKey.Xml);
            if (!rsa.VerifyData(bytes, CryptoConfig.MapNameToOID("SHA256"), signature))
                throw new InvalidDataException("Assinatura da versão não reconhecida.");
        }
        var value = json.Deserialize<Manifest>(Encoding.UTF8.GetString(bytes));
        Validate(value);
        return value;
    }
    internal static void Validate(Manifest value) {
        if (value == null || value.schema != 1 || value.platform != "windows-x64"
            || !VersionPattern.IsMatch(value.version ?? "") || value.package == null
            || (value.application_version != null && !VersionPattern.IsMatch(value.application_version))
            || value.package.name != "Farry-windows-x64.zip"
            || !Regex.IsMatch(value.package.sha256 ?? "", "^[a-f0-9]{64}$")
            || value.package.size < 1 || value.package.size > 8L * 1024 * 1024 * 1024)
            throw new InvalidDataException("Dados da versão inválidos.");
    }
    internal static string SafeEntry(string root, string name) {
        if (String.IsNullOrEmpty(name) || name.Contains(":") || name.Contains("\\") || name.StartsWith("/"))
            throw new InvalidDataException("Caminho inválido no pacote.");
        foreach (var segment in name.TrimEnd('/').Split('/')) {
            if (segment == "." || segment == ".." || segment.Length == 0 || segment.EndsWith(".") || segment.EndsWith(" ")
                || segment.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0
                || Regex.IsMatch(segment, @"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", RegexOptions.IgnoreCase))
                throw new InvalidDataException("Nome inválido no pacote.");
        }
        var path = Path.GetFullPath(Path.Combine(root, name.Replace('/', Path.DirectorySeparatorChar)));
        if (!path.StartsWith(Path.GetFullPath(root).TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Pacote fora da pasta permitida.");
        return path;
    }
    internal static void Extract(string zip, string destination) {
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase); long total = 0;
        using (var archive = ZipFile.OpenRead(zip)) {
            if (archive.Entries.Count > 100000) throw new InvalidDataException("Pacote excessivo.");
            foreach (var entry in archive.Entries) {
                var path = SafeEntry(destination, entry.FullName);
                if (!names.Add(path) || ((entry.ExternalAttributes >> 16) & 0xf000) == 0xa000)
                    throw new InvalidDataException("Entrada duplicada ou link no pacote.");
                total = checked(total + entry.Length);
                if (total > 16L * 1024 * 1024 * 1024) throw new InvalidDataException("Pacote excessivo.");
                if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(path); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                entry.ExtractToFile(path, false);
            }
        }
        foreach (var required in new[] { "QMoney.exe", "runtime/QMoneyService.exe", "Qt6Core.dll", "platforms/qwindows.dll" })
            if (!File.Exists(SafeEntry(destination, required))) throw new InvalidDataException("Pacote incompleto: " + required);
    }
}
internal sealed class Envelope { public string manifest { get; set; } public string signature { get; set; } }
internal sealed class Artifact { public string name { get; set; } public string sha256 { get; set; } public long size { get; set; } }
internal sealed class Manifest {
    public int schema { get; set; } public string version { get; set; }
    public string application_version { get; set; }
    public string platform { get; set; } public string notes { get; set; } public Artifact package { get; set; }
}


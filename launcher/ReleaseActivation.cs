using System;
using System.IO;
using System.Text;

internal static class ReleaseActivation {
    internal static string ResolveCurrent(string root) {
        var pointer = Path.Combine(root, "current.txt");
        if (!File.Exists(pointer)) return null;
        var version = File.ReadAllText(pointer).Trim();
        if (!ReleasePolicy.VersionPattern.IsMatch(version)) return null;
        return File.Exists(Path.Combine(root, "versions", version, "QMoney.exe")) ? version : null;
    }

    internal static void Activate(string root, string version, bool healthMarkerValid) {
        if (String.IsNullOrEmpty(root)) throw new ArgumentException("A pasta do launcher é obrigatória.", "root");
        if (!ReleasePolicy.VersionPattern.IsMatch(version ?? ""))
            throw new InvalidDataException("Versão de ativação inválida.");
        if (!healthMarkerValid)
            throw new IOException("A nova versão não confirmou prontidão. A versão anterior continua ativa.");
        if (!File.Exists(Path.Combine(root, "versions", version, "QMoney.exe")))
            throw new InvalidDataException("A versão preparada não contém QMoney.exe.");

        var pointer = Path.Combine(root, "current.txt");
        var hasCurrent = File.Exists(pointer);
        if (hasCurrent) {
            var current = File.ReadAllText(pointer).Trim();
            if (!ReleasePolicy.VersionPattern.IsMatch(current))
                throw new InvalidDataException("O ponteiro da versão instalada é inválido.");
            if (new Version(version) <= new Version(current))
                throw new InvalidDataException("Versão anterior ou já instalada.");
        }

        Directory.CreateDirectory(root);
        var next = Path.Combine(root, "current.next." + Guid.NewGuid().ToString("N"));
        try {
            File.WriteAllText(next, version, new UTF8Encoding(false));
            if (hasCurrent) File.Replace(next, pointer, Path.Combine(root, "previous.txt"));
            else File.Move(next, pointer);
        } finally {
            if (File.Exists(next)) File.Delete(next);
        }
    }

    internal static bool IsHealthMarkerValid(string marker) {
        if (String.IsNullOrEmpty(marker) || !File.Exists(marker)) return false;
        return String.Equals(File.ReadAllText(marker).Trim(), "ok", StringComparison.Ordinal);
    }
}

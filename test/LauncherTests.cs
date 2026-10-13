using System;
using System.IO;
using System.IO.Compression;
internal static class LauncherTests {
    static int assertions;
    static void Require(bool condition) { assertions++; if (!condition) throw new Exception("Assertion failed " + assertions); }
    static void Reject(Action action) { bool failed = false; try { action(); } catch (InvalidDataException) { failed = true; } Require(failed); }
    static void Main(string[] args) {
        var root = Path.Combine(Path.GetTempPath(), "farry-policy-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try {
            foreach (var name in new[] { "../escape.exe", "/absolute", "C:/escape", "a\\b", "a/../b", "CON.txt", "a./b", "a//b", "a/b:stream" })
                Reject(() => ReleasePolicy.SafeEntry(root, name));
            Require(ReleasePolicy.SafeEntry(root, "runtime/bin/file.dll").StartsWith(root));
            var release = new Manifest { schema = 1, version = "1.0.63", platform = "windows-x64",
                package = new Artifact { name = "Farry-windows-x64.zip", sha256 = new string('a',64), size = 3 } };
            ReleasePolicy.Validate(release);
            release.version = "01.0.63"; Reject(() => ReleasePolicy.Validate(release));
            release.version = "1.0.63"; release.package.size = -1; Reject(() => ReleasePolicy.Validate(release));
            var zip = Path.Combine(root, "bad.zip");
            using (var archive = ZipFile.Open(zip, ZipArchiveMode.Create)) { archive.CreateEntry("../escape.exe"); }
            Reject(() => ReleasePolicy.Extract(zip, Path.Combine(root, "app")));
            Require(!File.Exists(Path.Combine(root, "escape.exe")));
            var envelope = File.ReadAllText(args[0]);
            Require(ReleasePolicy.Decode(envelope).version == "1.0.63");
            Reject(() => ReleasePolicy.Decode(File.ReadAllText(args[1])));
            Console.WriteLine("Launcher policy: " + assertions + " assertions passed. No application was started.");
        } finally { Directory.Delete(root, true); }
    }
}

using System;
using System.IO;
using System.Text;

internal static class ActivationTests {
    private static int assertions;

    private static void Require(bool condition, string message) {
        assertions++;
        if (!condition) throw new Exception("Assertion failed: " + message);
    }

    private static void Reject(Action action) {
        var failed = false;
        try { action(); } catch (InvalidDataException) { failed = true; }
        Require(failed, "invalid activation should be rejected");
    }

    private static void CreateVersion(string root, string version) {
        var folder = Path.Combine(root, "versions", version);
        Directory.CreateDirectory(folder);
        File.WriteAllText(Path.Combine(folder, "QMoney.exe"), "test executable");
    }

    private static string ReadPointer(string root, string name) {
        return File.ReadAllText(Path.Combine(root, name)).Trim();
    }

    private static void WritePointer(string root, string name, string version) {
        File.WriteAllText(Path.Combine(root, name), version, new UTF8Encoding(false));
    }

    private static void TestFirstActivation(string root) {
        CreateVersion(root, "1.0.1");
        ReleaseActivation.Activate(root, "1.0.1", true);
        Require(ReadPointer(root, "current.txt") == "1.0.1", "first activation writes current pointer");
        Require(!File.Exists(Path.Combine(root, "previous.txt")), "first activation does not invent a previous pointer");
        Require(ReleaseActivation.ResolveCurrent(root) == "1.0.1", "offline current resolution finds installed version");
    }

    private static void TestUpgradePreservesPrevious(string root) {
        CreateVersion(root, "1.0.2");
        ReleaseActivation.Activate(root, "1.0.2", true);
        Require(ReadPointer(root, "current.txt") == "1.0.2", "upgrade activates new version");
        Require(ReadPointer(root, "previous.txt") == "1.0.1", "upgrade backs up prior current pointer");
        Require(ReleaseActivation.ResolveCurrent(root) == "1.0.2", "offline resolution follows current pointer");
    }

    private static void TestFailedReadinessLeavesPointers(string root) {
        CreateVersion(root, "1.0.3");
        WritePointer(root, "previous.txt", "0.9.9");
        var rejected = false;
        try { ReleaseActivation.Activate(root, "1.0.3", false); }
        catch (IOException) { rejected = true; }
        Require(rejected, "missing readiness is rejected");
        Require(ReadPointer(root, "current.txt") == "1.0.2", "failed readiness leaves current unchanged");
        Require(ReadPointer(root, "previous.txt") == "0.9.9", "failed readiness leaves previous unchanged");
    }

    private static void TestVersionAndMarkerValidation(string root) {
        CreateVersion(root, "1.0.0");
        CreateVersion(root, "1.0.2");
        Reject(() => ReleaseActivation.Activate(root, "1.0.2", true));
        Reject(() => ReleaseActivation.Activate(root, "1.0.1", true));
        Reject(() => ReleaseActivation.Activate(root, "01.0.3", true));

        var marker = Path.Combine(root, "health.txt");
        Require(!ReleaseActivation.IsHealthMarkerValid(marker), "missing health marker is invalid");
        File.WriteAllText(marker, "starting\n");
        Require(!ReleaseActivation.IsHealthMarkerValid(marker), "incomplete health marker is invalid");
        File.WriteAllText(marker, "ok\n");
        Require(ReleaseActivation.IsHealthMarkerValid(marker), "committed health marker is valid");
    }

    private static void TestInvalidOfflinePointer(string root) {
        var other = Path.Combine(root, "offline");
        Directory.CreateDirectory(other);
        WritePointer(other, "current.txt", "invalid");
        Require(ReleaseActivation.ResolveCurrent(other) == null, "invalid offline pointer is ignored");
    }

    internal static void Main() {
        var root = Path.Combine(Path.GetTempPath(), "farry-activation-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try {
            TestFirstActivation(root);
            TestUpgradePreservesPrevious(root);
            TestFailedReadinessLeavesPointers(root);
            TestVersionAndMarkerValidation(root);
            TestInvalidOfflinePointer(root);
            Console.WriteLine("Release activation: " + assertions + " assertions passed.");
        } finally {
            try { Directory.Delete(root, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}

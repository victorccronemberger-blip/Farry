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

internal sealed class Launcher : Form {
    private readonly string root;
    private readonly Label status = new Label { Dock = DockStyle.Top, Height = 105, Padding = new Padding(0, 20, 0, 0) };
    private readonly Button check = new Button { Text = "Verificar atualização", AutoSize = true };
    private readonly Button install = new Button { Text = "Instalar atualização", AutoSize = true, Enabled = false };
    private readonly Button open = new Button { Text = "Abrir QMoney", AutoSize = true };
    private readonly ProgressBar progress = new ProgressBar { Dock = DockStyle.Top, Height = 16 };
    private Manifest offered; private string signedEnvelope; private bool busy;
    internal Launcher(string installRoot) {
        root = installRoot; Directory.CreateDirectory(root);
        Text = "Farry · QMoney"; Size = new Size(620, 295); MinimumSize = Size;
        StartPosition = FormStartPosition.CenterScreen; Font = new Font("Segoe UI", 10);
        Padding = new Padding(24); BackColor = Color.FromArgb(241, 245, 241);
        var title = new Label { Text = "QMoney — versões e atualizações", Dock = DockStyle.Top, Height = 38,
            Font = new Font("Segoe UI", 16, FontStyle.Bold) };
        var actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 50 };
        actions.Controls.AddRange(new Control[] { open, check, install });
        Controls.Add(actions); Controls.Add(progress); Controls.Add(status); Controls.Add(title);
        check.Click += async (s, e) => await Check();
        install.Click += async (s, e) => await Install();
        open.Click += (s, e) => { try { StartCurrent(); } catch (Exception ex) { ShowFailure(ex); } };
        Shown += async (s, e) => await Check();
        FormClosing += (s, e) => { if (busy) { e.Cancel = true; status.Text = "Aguarde a operação terminar antes de fechar."; } };
    }
    private void SetBusy(bool value) { busy = value; check.Enabled = !value; open.Enabled = !value && Current() != null; install.Enabled = !value && offered != null; }
    private string Current() {
        var pointer = Path.Combine(root, "current.txt");
        if (!File.Exists(pointer)) return null;
        var version = File.ReadAllText(pointer).Trim();
        if (!ReleasePolicy.VersionPattern.IsMatch(version)) return null;
        return File.Exists(Path.Combine(root, "versions", version, "QMoney.exe")) ? version : null;
    }
    private bool AlreadyRunning() { return Process.GetProcessesByName("QMoney").Length > 0; }
    private void StartCurrent() {
        var current = Current();
        if (current == null) throw new InvalidOperationException("Instale a primeira versão pelo Farry.");
        var folder = Path.Combine(root, "versions", current);
        Process.Start(new ProcessStartInfo(Path.Combine(folder, "QMoney.exe")) { WorkingDirectory = folder, UseShellExecute = true });
    }
    private void ShowFailure(Exception ex) {
        status.Text = "Operação não concluída. A versão instalada foi preservada.\n" + ex.Message;
    }
    private async Task Check() {
        if (busy) return; SetBusy(true); offered = null;
        status.Text = "Consultando o servidor de versões…";
        try {
            using (var client = Client(20)) {
                var bytes = await DownloadSmall(client, ReleasePolicy.Origin + "/api/releases/latest", 65536);
                signedEnvelope = Encoding.UTF8.GetString(bytes);
            }
            var candidate = ReleasePolicy.Decode(signedEnvelope);
            var current = Current();
            if (current != null && new Version(candidate.version) <= new Version(current))
                status.Text = "Versão " + current + " instalada. Nenhuma atualização disponível.";
            else { offered = candidate; status.Text = "Disponível: " + candidate.version + "\n" + (candidate.notes ?? ""); }
        } catch (Exception ex) { ShowFailure(ex); }
        finally { SetBusy(false); }
    }
    private static HttpClient Client(int seconds) {
        return new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = TimeSpan.FromSeconds(seconds) };
    }
    private static async Task<HttpResponseMessage> Get(HttpClient client, string url) {
        for (int i = 0; i < 5; i++) {
            var uri = new Uri(url);
            if (uri.Scheme != "https" || !String.IsNullOrEmpty(uri.UserInfo)
                || !(uri.Host == new Uri(ReleasePolicy.Origin).Host || uri.Host == "release-assets.githubusercontent.com"
                    || uri.Host == "objects.githubusercontent.com")) throw new InvalidDataException("Destino de download não autorizado.");
            var result = await client.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead);
            if ((int)result.StatusCode >= 300 && (int)result.StatusCode < 400) {
                var location = result.Headers.Location; result.Dispose();
                if (location == null) throw new InvalidDataException("Redirecionamento inválido.");
                url = new Uri(uri, location).AbsoluteUri; continue;
            }
            if (!result.IsSuccessStatusCode) {
                var code = (int)result.StatusCode; result.Dispose();
                throw new IOException(code == 404 ? "Nenhuma versão publicada ainda." : "Servidor indisponível (HTTP " + code + ").");
            }
            return result;
        }
        throw new IOException("Muitos redirecionamentos.");
    }
    private static async Task<byte[]> DownloadSmall(HttpClient client, string url, int limit) {
        using (var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30)))
        using (var response = await Get(client, url))
        using (var source = await response.Content.ReadAsStreamAsync())
        using (var output = new MemoryStream()) {
            var buffer = new byte[8192]; int count;
            while ((count = await source.ReadAsync(buffer, 0, buffer.Length, deadline.Token)) != 0) {
                if (output.Length + count > limit) throw new InvalidDataException("Resposta excessiva.");
                output.Write(buffer, 0, count);
            }
            return output.ToArray();
        }
    }
    private async Task Install() {
        if (busy || offered == null) return;
        if (AlreadyRunning()) { status.Text = "Feche o QMoney com segurança antes de instalar a atualização."; return; }
        var release = offered; SetBusy(true);
        var work = Path.Combine(root, "staging", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(work);
        try {
            var current = Current();
            if (current != null && new Version(release.version) <= new Version(current)) throw new InvalidDataException("Versão anterior ou já instalada.");
            status.Text = "Baixando QMoney " + release.version + "…";
            var zip = Path.Combine(work, "package.zip");
            using (var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(30)))
            using (var client = Client(1800))
            using (var response = await Get(client, ReleasePolicy.Origin + "/downloads/v" + release.version + "/" + release.package.name))
            using (var source = await response.Content.ReadAsStreamAsync())
            using (var output = new FileStream(zip, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                var buffer = new byte[131072]; long total = 0; int count;
                while ((count = await source.ReadAsync(buffer, 0, buffer.Length, deadline.Token)) != 0) {
                    total += count; if (total > release.package.size) throw new InvalidDataException("Tamanho do pacote incorreto.");
                    await output.WriteAsync(buffer, 0, count); progress.Value = (int)(total * 100 / release.package.size);
                }
                if (total != release.package.size) throw new InvalidDataException("Download incompleto.");
            }
            status.Text = "Verificando e extraindo o pacote…";
            await Task.Run(() => {
                using (var sha = SHA256.Create()) using (var file = File.OpenRead(zip)) {
                    var hash = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
                    if (hash != release.package.sha256) throw new InvalidDataException("SHA-256 do pacote não confere.");
                }
                ReleasePolicy.Extract(zip, Path.Combine(work, "app"));
            });
            if (AlreadyRunning()) throw new IOException("O QMoney foi aberto durante o download. Feche-o e tente novamente.");
            var destination = Path.Combine(root, "versions", release.version);
            Directory.CreateDirectory(Path.GetDirectoryName(destination));
            if (Directory.Exists(destination)) {
                // Preserve unsuccessful earlier installs for inspection instead of overwriting them.
                Directory.Move(destination, destination + ".previous-" + Guid.NewGuid().ToString("N"));
            }
            Directory.Move(Path.Combine(work, "app"), destination);
            File.WriteAllText(Path.Combine(destination, "release-envelope.json"), signedEnvelope, new UTF8Encoding(false));
            var marker = Path.Combine(work, "health.txt");
            status.Text = "Abrindo a nova versão para verificar o motor local…";
            var process = Process.Start(new ProcessStartInfo(Path.Combine(destination, "QMoney.exe"), "--update-health \"" + marker + "\"") {
                WorkingDirectory = destination, UseShellExecute = false });
            var until = DateTime.UtcNow.AddSeconds(120);
            while (!File.Exists(marker) && !process.HasExited && DateTime.UtcNow < until) await Task.Delay(500);
            if (!File.Exists(marker)) throw new IOException("A nova versão não confirmou prontidão. O atalho continua apontando para a versão anterior. Feche a janela de teste antes de abrir a anterior.");
            var pointer = Path.Combine(root, "current.txt");
            var next = Path.Combine(root, "current.next");
            File.WriteAllText(next, release.version, new UTF8Encoding(false));
            if (File.Exists(pointer)) File.Replace(next, pointer, Path.Combine(root, "previous.txt"));
            else File.Move(next, pointer);
            offered = null; status.Text = "QMoney " + release.version + " instalado e pronto.";
        } catch (Exception ex) { ShowFailure(ex); }
        finally {
            var prefix = Path.GetFullPath(Path.Combine(root, "staging")) + Path.DirectorySeparatorChar;
            if (Path.GetFullPath(work).StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) {
                try { Directory.Delete(work, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            }
            SetBusy(false);
        }
    }
    [STAThread] private static void Main() {
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Farry");
        using (var mutex = new Mutex(false, "Local\\FarryLauncher")) {
            bool acquired;
            try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
            if (!acquired) { MessageBox.Show("O launcher Farry já está aberto."); return; }
            try {
                if (Path.GetFileName(Application.ExecutablePath).Equals("FarrySetup.exe", StringComparison.OrdinalIgnoreCase)) {
                    if (MessageBox.Show("Instalar o launcher Farry para este usuário? As contas e configurações do QMoney serão preservadas.", "Instalar Farry", MessageBoxButtons.YesNo) != DialogResult.Yes) return;
                    Directory.CreateDirectory(root);
                    var target = Path.Combine(root, "FarryLauncher.exe");
                    File.Copy(Application.ExecutablePath, target, true);
                    CreateShortcut(target, root, Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory));
                    CreateShortcut(target, root, Environment.GetFolderPath(Environment.SpecialFolder.Programs));
                }
                Application.Run(new Launcher(root));
            } catch (Exception ex) { MessageBox.Show(ex.Message, "Farry", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            finally { mutex.ReleaseMutex(); }
        }
    }
    private static void CreateShortcut(string target, string root, string folder) {
        var type = Type.GetTypeFromProgID("WScript.Shell");
        dynamic shell = Activator.CreateInstance(type);
        dynamic link = shell.CreateShortcut(Path.Combine(folder, "Farry - QMoney.lnk"));
        link.TargetPath = target; link.WorkingDirectory = root; link.Description = "Abrir e atualizar QMoney";
        link.Save();
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link);
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
    }
}

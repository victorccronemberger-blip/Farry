param([Parameter(Mandatory=$true)][string]$ProjectRoot, [switch]$Apply)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\')
$prefix = $root + '\'
if (-not (Test-Path -LiteralPath (Join-Path $root 'moneymin\web\server.py'))) { throw 'Projeto não reconhecido.' }
$targets = @()
$pytest = Join-Path $root '.pytest_cache'
if (Test-Path -LiteralPath $pytest) { $targets += Get-Item -LiteralPath $pytest }
foreach ($scope in @('moneymin','test','scripts','packaging','app')) {
    $directory = Join-Path $root $scope
    if (Test-Path -LiteralPath $directory) {
        $targets += Get-ChildItem -LiteralPath $directory -Directory -Recurse -Filter '__pycache__'
    }
}
foreach ($target in $targets) {
    $resolved = [IO.Path]::GetFullPath($target.FullName)
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
        ($target.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Cache fora da raiz ou link: operação recusada.' }
}
Write-Output ('Caches regeneráveis identificados: ' + $targets.Count)
if (-not $Apply) { $targets.FullName; return }
# Use the Windows recycle bin; do not permanently delete project data.
Add-Type -AssemblyName Microsoft.VisualBasic
foreach ($target in $targets) {
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($target.FullName,
        [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
        [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)
}
Write-Output ('Caches enviados à Lixeira: ' + $targets.Count)

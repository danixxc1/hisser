[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$DevPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$RuntimeRoot = Join-Path $ProjectRoot 'runtime'
$AssetRoot = Join-Path $ProjectRoot 'assets'
$BuildRoot = Join-Path $ProjectRoot 'build'
$DistRoot = Join-Path $ProjectRoot 'dist'
$PackageRoot = Join-Path $DistRoot 'Hisser'

function Assert-WorkspacePath([string]$Path) {
    $Full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $Full.StartsWith($ProjectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build path is outside the source workspace: $Full"
    }
    $Current = $Full
    while ($Current.Length -ge $ProjectRoot.Length) {
        if (Test-Path -LiteralPath $Current) {
            $Item = Get-Item -LiteralPath $Current -Force
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing to build through a linked directory: $Current"
            }
        }
        if ($Current -eq $ProjectRoot) { break }
        $Current = Split-Path -Path $Current -Parent
    }
}

foreach ($Path in @($BuildRoot, $DistRoot, $PackageRoot, $RuntimeRoot, $AssetRoot)) {
    Assert-WorkspacePath $Path
}
foreach ($Path in @($DevPython, (Join-Path $ProjectRoot 'main.py'), (Join-Path $AssetRoot 'hisser.ico'))) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required build input is missing: $Path" }
}
foreach ($Name in @('whisper-cli.exe', 'ffmpeg.exe', 'ffprobe.exe', 'provenance.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot $Name) -PathType Leaf)) {
        throw "Runtime file $Name is missing. Run scripts/prepare_runtime.py before building."
    }
}
foreach ($Tree in @($RuntimeRoot, $AssetRoot)) {
    $Links = @(Get-ChildItem -LiteralPath $Tree -Recurse -Force | Where-Object {
        ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    })
    if ($Links.Count -gt 0) { throw "Build inputs contain a linked file or directory: $($Links[0].FullName)" }
}

$Version = (& $DevPython -c 'import PyInstaller; print(PyInstaller.__version__)').Trim()
if ($LASTEXITCODE -ne 0 -or $Version -ne '6.22.3') {
    throw "This build requires isolated .venv PyInstaller 6.22.3; found '$Version'. No packages were installed."
}
$ExistingBuildExe = Join-Path $PackageRoot 'Hisser.exe'
$Running = @(Get-CimInstance Win32_Process -Filter "Name = 'Hisser.exe'" | Where-Object {
    $_.ExecutablePath -and [string]::Equals($_.ExecutablePath, $ExistingBuildExe, [StringComparison]::OrdinalIgnoreCase)
})
if ($Running.Count -gt 0) { throw 'Close the copy of Hisser running from dist before rebuilding.' }

New-Item -ItemType Directory -Path $BuildRoot, $DistRoot -Force | Out-Null
$env:PYINSTALLER_CONFIG_DIR = Join-Path $BuildRoot 'cache'
$Arguments = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name', 'Hisser', '--contents-directory', '_internal',
    '--icon', (Join-Path $AssetRoot 'hisser.ico'),
    '--distpath', $DistRoot, '--workpath', (Join-Path $BuildRoot 'pyinstaller'),
    '--specpath', $BuildRoot,
    '--add-data', ($AssetRoot + ':assets'),
    '--add-data', ($RuntimeRoot + ':runtime')
)
# These packages are for development/inspection and are not part of Hisser.
# ReportLab, Pillow, tkinter and the standard library remain available.
foreach ($Module in @(
    'pytest', 'psutil', 'pymupdf', 'fitz', 'pymupdf4llm', 'pymupdf_layout',
    'numpy', 'onnxruntime', 'scipy', 'pandas', 'matplotlib', 'torch', 'tensorflow',
    'cv2', 'IPython', 'jupyter', 'notebook', 'networkx', 'yaml', 'tabulate',
    'google.protobuf', 'tkinter.test'
)) {
    $Arguments += @('--exclude-module', $Module)
}
$Arguments += (Join-Path $ProjectRoot 'main.py')
Push-Location $ProjectRoot
try {
    & $DevPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}
$Exe = Join-Path $PackageRoot 'Hisser.exe'
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw 'The build did not create Hisser.exe.' }
$Manifest = [ordered]@{
    name = 'Hisser'
    version = '1.0.0'
    built_utc = [DateTime]::UtcNow.ToString('o')
    pyinstaller = $Version
    exe_sha256 = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant()
    bytes = [long](Get-ChildItem -LiteralPath $PackageRoot -File -Recurse | Measure-Object Length -Sum).Sum
    model_included = $false
    portable = $true
    model_location = 'data\models\ggml-large-v3-q5_0.bin (relative to Hisser.exe)'
}
$ManifestText = $Manifest | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText((Join-Path $PackageRoot 'build-manifest.json'), $ManifestText + "`n", [Text.UTF8Encoding]::new($false))
Write-Host "Built $Exe"
Write-Host "Package size: $($Manifest.bytes) bytes. The local model is stored separately."
Write-Host 'Next developer step: run scripts/package-portable.ps1 in the regular Windows user session.'

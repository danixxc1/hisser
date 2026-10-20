[CmdletBinding()]
param([ValidateSet('cpu', 'cuda')][string]$Backend = 'cpu')

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$DevPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$RuntimeRoot = Join-Path $ProjectRoot 'runtime'
$AssetRoot = Join-Path $ProjectRoot 'assets'
$BuildRoot = Join-Path $ProjectRoot 'build'
$DistRoot = Join-Path $ProjectRoot 'dist'
$PackageRoot = Join-Path $DistRoot 'Hisser'
$CpuRuntimeFiles = @(
    'whisper-cli.exe', 'whisper.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-cpu-x64.dll',
    'ffmpeg.exe', 'ffprobe.exe', 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'vcomp140.dll'
)
$CudaRuntimeFiles = @(
    'whisper-cli.exe', 'whisper.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-cpu-x64.dll', 'ggml-cuda.dll',
    'cublas64_11.dll', 'cublasLt64_11.dll', 'cudart64_110.dll', 'nvrtc64_112_0.dll', 'nvrtc-builtins64_118.dll',
    'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'vcomp140.dll'
)

function Test-GpuRuntimeFile([string]$Name) {
    return $Name -match '^(ggml-cuda|cublas|cudart|nvrtc).*\.dll$'
}

function Assert-RuntimeFile([string]$Path, [string]$Relative) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path).Length -le 0) {
        throw "Runtime file $Relative is missing or empty. Prepare the requested backend before building."
    }
}

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

function Remove-DuplicateCudaLibraries([string]$Folder) {
    $FullFolder = [IO.Path]::GetFullPath($Folder).TrimEnd('\')
    if (-not [string]::Equals($FullFolder, $PackageRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'CUDA deduplication is restricted to this build''s dist\Hisser folder.'
    }
    Assert-WorkspacePath $FullFolder
    $Removed = [Collections.Generic.List[object]]::new()
    # PyInstaller may collect these subprocess dependencies at _internal's root.
    # Python does not load CUDA. The owned CLI uses runtime\cuda as its cwd, so
    # retain that complete copy and remove only identical root-level duplicates.
    foreach ($Name in @('cublas64_11.dll', 'cublasLt64_11.dll')) {
        $Duplicate = Join-Path $FullFolder ('_internal\' + $Name)
        if (-not (Test-Path -LiteralPath $Duplicate)) { continue }
        $Bundled = Join-Path $FullFolder ('_internal\runtime\cuda\' + $Name)
        $Prepared = Join-Path $RuntimeRoot ('cuda\' + $Name)
        foreach ($Path in @($Duplicate, $Bundled, $Prepared)) {
            Assert-WorkspacePath $Path
            Assert-RuntimeFile $Path $Name
        }
        $ExpectedHash = (Get-FileHash -LiteralPath $Prepared -Algorithm SHA256).Hash
        $BundledHash = (Get-FileHash -LiteralPath $Bundled -Algorithm SHA256).Hash
        $DuplicateHash = (Get-FileHash -LiteralPath $Duplicate -Algorithm SHA256).Hash
        if ($ExpectedHash -ne $BundledHash -or $BundledHash -ne $DuplicateHash) {
            throw "The duplicate $Name differs from the prepared CUDA library; preserved for inspection."
        }
        $Bytes = [long](Get-Item -LiteralPath $Duplicate).Length
        Remove-Item -LiteralPath $Duplicate -Force
        $Removed.Add([pscustomobject]@{ name = $Name; bytes = $Bytes; sha256 = $ExpectedHash.ToLowerInvariant() })
    }
    return $Removed.ToArray()
}

foreach ($Path in @($BuildRoot, $DistRoot, $PackageRoot, $RuntimeRoot, $AssetRoot)) {
    Assert-WorkspacePath $Path
}
foreach ($Path in @($DevPython, (Join-Path $ProjectRoot 'main.py'), (Join-Path $AssetRoot 'hisser.ico'))) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required build input is missing: $Path" }
}
foreach ($Name in ($CpuRuntimeFiles + 'provenance.json')) {
    Assert-RuntimeFile (Join-Path $RuntimeRoot $Name) $Name
}
if ($Backend -eq 'cuda') {
    foreach ($Name in $CudaRuntimeFiles) {
        Assert-RuntimeFile (Join-Path $RuntimeRoot ('cuda\' + $Name)) ('cuda\' + $Name)
    }
}
foreach ($Tree in @($RuntimeRoot, $AssetRoot)) {
    $Links = @(Get-ChildItem -LiteralPath $Tree -Recurse -Force | Where-Object {
        ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    })
    if ($Links.Count -gt 0) { throw "Build inputs contain a linked file or directory: $($Links[0].FullName)" }
}
if ($Backend -eq 'cpu') {
    $StrayGpuFiles = @(Get-ChildItem -LiteralPath $RuntimeRoot -File -Recurse -Force | Where-Object {
        -not $_.FullName.StartsWith((Join-Path $RuntimeRoot 'cuda') + '\', [StringComparison]::OrdinalIgnoreCase) -and
        (Test-GpuRuntimeFile $_.Name)
    })
    if ($StrayGpuFiles.Count -gt 0) { throw "GPU DLLs exist outside runtime\cuda; a CPU-only build would include them: $($StrayGpuFiles[0].FullName)" }
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
    '--add-data', ($AssetRoot + ':assets')
)
# Include CUDA only when requested. A CPU fallback package must not retain its
# large GPU DLLs just because they were downloaded for a comparison.
foreach ($RuntimeItem in (Get-ChildItem -LiteralPath $RuntimeRoot -Force)) {
    if ($RuntimeItem.Name -eq 'cuda' -and $Backend -eq 'cpu') { continue }
    $RuntimeDestination = if ($RuntimeItem.PSIsContainer) { 'runtime/' + $RuntimeItem.Name } else { 'runtime' }
    $Arguments += @('--add-data', ($RuntimeItem.FullName + ':' + $RuntimeDestination))
}
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
$PackagedRuntime = Join-Path $PackageRoot '_internal\runtime'
foreach ($Name in $CpuRuntimeFiles) { Assert-RuntimeFile (Join-Path $PackagedRuntime $Name) $Name }
if ($Backend -eq 'cuda') {
    foreach ($Name in $CudaRuntimeFiles) {
        Assert-RuntimeFile (Join-Path $PackagedRuntime ('cuda\' + $Name)) ('cuda\' + $Name)
    }
    $RemovedCudaDuplicates = @(Remove-DuplicateCudaLibraries $PackageRoot)
} else {
    $RemovedCudaDuplicates = @()
    $PackagedGpuFiles = @(Get-ChildItem -LiteralPath (Join-Path $PackageRoot '_internal') -File -Recurse -Force | Where-Object { Test-GpuRuntimeFile $_.Name })
    if ((Test-Path -LiteralPath (Join-Path $PackagedRuntime 'cuda')) -or $PackagedGpuFiles.Count -gt 0) {
        throw 'The CPU-only build unexpectedly retained CUDA components. No deployable build manifest was written.'
    }
}
$RemovedCudaDuplicateBytes = [long]0
foreach ($RemovedDuplicate in $RemovedCudaDuplicates) { $RemovedCudaDuplicateBytes += $RemovedDuplicate.bytes }
$AppVersion = (& $DevPython -c 'from hisser import __version__; print(__version__)').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not read the Hisser application version.' }
$Manifest = [ordered]@{
    name = 'Hisser'
    version = $AppVersion
    built_utc = [DateTime]::UtcNow.ToString('o')
    pyinstaller = $Version
    exe_sha256 = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant()
    bytes = [long](Get-ChildItem -LiteralPath $PackageRoot -File -Recurse -Force | Measure-Object Length -Sum).Sum
    model_included = $false
    portable = $true
    backend = $Backend
    removed_cuda_duplicate_bytes = $RemovedCudaDuplicateBytes
    removed_cuda_duplicates = @($RemovedCudaDuplicates)
    model_location = 'data\models\<filename selected by transcription-profile.json> (relative to Hisser.exe)'
}
$ManifestText = $Manifest | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText((Join-Path $PackageRoot 'build-manifest.json'), $ManifestText + "`n", [Text.UTF8Encoding]::new($false))
Write-Host "Built $Exe"
Write-Host "Package size: $($Manifest.bytes) bytes. The local model is stored separately."
Write-Host 'Next developer step: run scripts/package-portable.ps1 in the regular Windows user session.'

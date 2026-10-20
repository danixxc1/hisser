[CmdletBinding()]
param(
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$SourceSha256 = '0aa2b1de2a5698b20a23e93d539a9a8e82ca0117496c5bdf05d198805f42bb3b',
    [string]$OutputDirectory = '',
    [switch]$RedistOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $ProjectRoot 'qa\distribution-runtime' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Choose a fresh output directory.' }
$SourceCommit = '946fcce07b6dcd0331c8cc609192aeff5e1924f8'
$SourceUrl = 'https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/' + $SourceCommit
$VsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $VsWhere)) { throw 'Visual Studio Installer vswhere.exe is required on the hosted runner.' }
$VsInventoryLines = @(& $VsWhere -all -products '*' -format json -utf8)
if ($LASTEXITCODE -ne 0) { throw "vswhere failed with exit code $LASTEXITCODE" }
$VsInventoryText = [string]::Join([Environment]::NewLine, $VsInventoryLines)
Write-Host 'Visual Studio installation inventory (hosted-runner diagnostics):'
Write-Host $VsInventoryText
if ([string]::IsNullOrWhiteSpace($VsInventoryText)) { throw 'vswhere returned no installation inventory.' }
$VsInstallations = @($VsInventoryText | ConvertFrom-Json -ErrorAction Stop)
$VsRecord = $VsInstallations | Where-Object {
    $_.productId -eq 'Microsoft.VisualStudio.Product.Enterprise' -and
    $_.isComplete -and -not $_.isPrerelease -and
    ([version]$_.installationVersion).Major -in @(17, 18) -and
    (Test-Path -LiteralPath (Join-Path $_.installationPath 'VC\Redist\MSVC')) -and
    (Test-Path -LiteralPath (Join-Path $_.installationPath 'VC\Tools\MSVC'))
} | Sort-Object { [version]$_.installationVersion } -Descending | Select-Object -First 1
if (-not $VsRecord) { throw 'No complete, stable Visual Studio 2022/2026 Enterprise C++ installation with redistribution files was found. See the inventory above.' }
$VsInstallation = [string]$VsRecord.installationPath
$VsYear = if (([version]$VsRecord.installationVersion).Major -eq 18) { '2026' } else { '2022' }
$VsLabel = "Visual Studio $VsYear Enterprise"
$RedistLicenseUrl = "https://learn.microsoft.com/en-us/visualstudio/releases/$VsYear/redistribution"
Write-Host "Selected $VsLabel version $($VsRecord.installationVersion)"
$RedistRoot = Join-Path $VsInstallation 'VC\Redist\MSVC'
$RedistVersion = Get-ChildItem -LiteralPath $RedistRoot -Directory |
    Where-Object { $_.Name -match '^\d+\.\d+\.\d+(\.\d+)?$' } |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
if (-not $RedistVersion) { throw 'Visual Studio contains no versioned redistributable directory.' }
$RedistX64 = Join-Path $RedistVersion.FullName 'x64'
$CrtDirectory = Get-ChildItem -LiteralPath $RedistX64 -Directory -Filter 'Microsoft.VC*.CRT' | Select-Object -First 1
$OpenMpDirectory = Get-ChildItem -LiteralPath $RedistX64 -Directory -Filter 'Microsoft.VC*.OpenMP' | Select-Object -First 1
if (-not $CrtDirectory -or -not $OpenMpDirectory) { throw 'The x64 CRT and OpenMP redistributable directories are required.' }
$OverlayDirectory = Join-Path $OutputDirectory 'runtime-overlay'
$SourcesDirectory = Join-Path $OutputDirectory 'corresponding-source'
$ReportsDirectory = Join-Path $OutputDirectory 'reports'
New-Item -ItemType Directory -Path $OverlayDirectory, $SourcesDirectory, $ReportsDirectory | Out-Null
$Records = @()
$MsFileSetHash = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
foreach ($Name in @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'vcomp140.dll')) {
    $OriginDirectory = if ($Name -eq 'vcomp140.dll') { $OpenMpDirectory.FullName } else { $CrtDirectory.FullName }
    $Origin = Join-Path $OriginDirectory $Name
    if (-not (Test-Path -LiteralPath $Origin -PathType Leaf)) { throw "Missing redistributable: $Name" }
    $Signature = Get-AuthenticodeSignature -LiteralPath $Origin
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
        throw "Redistributable signature is not a valid Microsoft signature: $Name"
    }
    $Target = Join-Path $OverlayDirectory $Name
    Copy-Item -LiteralPath $Origin -Destination $Target
    $MsFileSetHash.AppendData([IO.File]::ReadAllBytes($Target))
    $Records += [ordered]@{
        name = $Name
        size = (Get-Item -LiteralPath $Target).Length
        sha256 = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
        file_version = (Get-Item -LiteralPath $Target).VersionInfo.FileVersion
        source = "$VsLabel VC/Redist/MSVC/$($RedistVersion.Name)/x64/$($OriginDirectory | Split-Path -Leaf)/$Name"
        signature_status = [string]$Signature.Status
        signer = $Signature.SignerCertificate.Subject
        redistribution_list = $RedistLicenseUrl
    }
}
$MsFileSetSha256 = [Convert]::ToHexString($MsFileSetHash.GetHashAndReset()).ToLowerInvariant()
$MsFileSetHash.Dispose()
$CudaOverlayDirectory = Join-Path $OverlayDirectory 'cuda'
New-Item -ItemType Directory -Path $CudaOverlayDirectory | Out-Null
foreach ($Record in $Records) {
    Copy-Item -LiteralPath (Join-Path $OverlayDirectory $Record.name) -Destination $CudaOverlayDirectory
}

function Write-PublicProvenance {
    $Components = @([ordered]@{
        name = 'Microsoft Visual C++ Redistributables'
        version = $RedistVersion.Name
        source_url = $RedistLicenseUrl
        source_sha256 = $MsFileSetSha256
        source_hash_kind = 'SHA-256 of the concatenated original DLL bytes in source_files order; not an archive hash'
        source_files = @($Records | ForEach-Object { $_.name })
        license = "Microsoft Visual Studio $VsYear license and REDIST list"
        build_flags = @()
    })
    if (Test-Path -LiteralPath (Join-Path $OverlayDirectory 'ffmpeg.exe')) {
        $Components += [ordered]@{
            name = 'FFmpeg'
            version = '9.0.2'
            source_url = $SourceUrl
            source_sha256 = $SourceSha256.ToLowerInvariant()
            source_commit = $SourceCommit
            license = 'LGPL-2.1-or-later'
            build_flags = @('--toolchain=msvc', '--target-os=win64', '--arch=x86_64',
                '--disable-autodetect', '--disable-network', '--disable-gpl', '--disable-nonfree',
                '--disable-ffplay', '--disable-doc', '--disable-debug', '--disable-x86asm',
                '--enable-w32threads', '--enable-static', '--disable-shared')
        }
    }
    $PublicFiles = @(Get-ChildItem -LiteralPath $OverlayDirectory -Recurse -File |
        Where-Object { $_.Name -ne 'provenance.json' } | Sort-Object FullName | ForEach-Object {
            [ordered]@{
                path = [IO.Path]::GetRelativePath($OverlayDirectory, $_.FullName).Replace('\', '/')
                size = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        })
    [ordered]@{ format_version = 1; components = $Components; files = $PublicFiles } |
        ConvertTo-Json -Depth 9 | Set-Content -LiteralPath (Join-Path $OverlayDirectory 'provenance.json') -Encoding utf8
}

$Manifest = [ordered]@{
    format_version = 1
    build_environment = "GitHub-hosted Windows runner; $VsLabel"
    runner_image = $env:ImageOS
    runner_image_version = $env:ImageVersion
    visual_studio_version = $VsRecord.installationVersion
    redistributable_version = $RedistVersion.Name
    microsoft_files = $Records
    ffmpeg = [ordered]@{ version = '9.0.2'; source_commit = $SourceCommit; source_url = $SourceUrl; source_sha256 = $SourceSha256.ToLowerInvariant(); modified = $false }
}
$Manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ReportsDirectory 'distribution-runtime.json') -Encoding utf8
Copy-Item -LiteralPath $PSCommandPath -Destination $SourcesDirectory
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build-ffmpeg-release.sh') -Destination $SourcesDirectory
if ($RedistOnly) { Write-PublicProvenance; Write-Output 'Verified Visual Studio redistributables are ready.'; return }

$Archive = Join-Path $SourcesDirectory 'ffmpeg-9.0.2-source.tar.gz'
Invoke-WebRequest -Uri $SourceUrl -OutFile $Archive -TimeoutSec 300 -MaximumRetryCount 3 -RetryIntervalSec 5
if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ine $SourceSha256) { throw 'The FFmpeg source archive SHA-256 does not match the pinned upstream source.' }
$WorkDirectory = Join-Path $ProjectRoot 'qa\ffmpeg-release-work'
if (Test-Path -LiteralPath $WorkDirectory) { throw 'A previous FFmpeg work directory exists; preserve it and use a clean checkout.' }
New-Item -ItemType Directory -Path $WorkDirectory | Out-Null
& tar.exe -xf $Archive -C $WorkDirectory
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg source extraction failed.' }
$SourceDirectory = Join-Path $WorkDirectory ('FFmpeg-' + $SourceCommit)
if (-not (Test-Path -LiteralPath (Join-Path $SourceDirectory 'configure'))) { throw 'The extracted FFmpeg source is incomplete.' }
$BuildDirectory = Join-Path $WorkDirectory 'build'
$FfmpegOutputDirectory = Join-Path $WorkDirectory 'output'

$DevShellModule = Join-Path $VsInstallation 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll'
Import-Module $DevShellModule
Enter-VsDevShell -VsInstallPath $VsInstallation -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64'
$Manifest.compiler = [ordered]@{
    name = 'Microsoft C/C++'
    file_version = (Get-Item -LiteralPath (Get-Command cl.exe -ErrorAction Stop).Source).VersionInfo.FileVersion
    target_architecture = 'x64'
}
$Bash = 'C:\msys64\usr\bin\bash.exe'
if (-not (Test-Path -LiteralPath $Bash)) { throw 'The GitHub runner must have MSYS2 installed.' }
# Keep MSVC's linker before MSYS2's unrelated link.exe on PATH.
$env:PATH = $env:PATH + ';C:\msys64\usr\bin'
$env:MSYS2_PATH_TYPE = 'inherit'
$ShellScript = (Join-Path $PSScriptRoot 'build-ffmpeg-release.sh').Replace('\', '/')
& $Bash --noprofile --norc $ShellScript $SourceDirectory $BuildDirectory $FfmpegOutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'The FFmpeg MSVC build or license verification failed.' }
foreach ($Name in @('ffmpeg.exe', 'ffprobe.exe')) {
    $Target = Join-Path $OverlayDirectory $Name
    Copy-Item -LiteralPath (Join-Path $FfmpegOutputDirectory $Name) -Destination $Target
    $Manifest.ffmpeg[$Name] = [ordered]@{
        size = (Get-Item -LiteralPath $Target).Length
        sha256 = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
foreach ($Name in @('COPYING.LGPLv2.1', 'config.h', 'config_components.h', 'config.mak', 'ffmpeg-version.txt', 'ffmpeg-license.txt', 'ffmpeg-buildconf.txt', 'ffprobe-version.txt')) {
    Copy-Item -LiteralPath (Join-Path $FfmpegOutputDirectory $Name) -Destination $SourcesDirectory
}
$Manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ReportsDirectory 'distribution-runtime.json') -Encoding utf8
Write-PublicProvenance
Write-Output 'Redistribution runtime, FFmpeg source and build reports are ready.'

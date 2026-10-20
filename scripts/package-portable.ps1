[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$BuildDirectory = '',
    [string]$Destination = '',
    [string]$DataDirectory = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
if (-not $BuildDirectory) { $BuildDirectory = Join-Path $ProjectRoot 'dist\Hisser' }
$BuildDirectory = [IO.Path]::GetFullPath($BuildDirectory).TrimEnd('\')
$Desktop = [Environment]::GetFolderPath('DesktopDirectory')
$LocalRoot = [Environment]::GetFolderPath('LocalApplicationData')
$Documents = [Environment]::GetFolderPath('MyDocuments')
if (-not $Desktop -or -not $LocalRoot -or -not $Documents) {
    throw 'Windows could not resolve the current user''s Desktop, Documents and local data folders.'
}
$Desktop = [IO.Path]::GetFullPath($Desktop).TrimEnd('\')
if (-not $Destination) { $Destination = Join-Path $Documents 'Tools\Hiss' }
$PortableRoot = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
$PortableParent = Split-Path -Path $PortableRoot -Parent
$PortableName = Split-Path -Path $PortableRoot -Leaf
$DesktopShortcut = Join-Path $Desktop 'Hisser.lnk'
$ShortcutTouched = $false
$ShortcutBefore = $null
$LegacyData = Join-Path $LocalRoot 'Hisser'
$Token = [Guid]::NewGuid().ToString('N')
$StageRoot = Join-Path $PortableParent ($PortableName + '.preparing-' + $Token)
$BackupRoot = Join-Path $PortableParent ($PortableName + '.previous-' + $Token)
$ApplicationId = 'Hisser.LocalTranscriber.1'
$OldMoved = $false
$NewMoved = $false
$DataMoved = $false
$Committed = $false
$DataOrigin = ''

function Test-Inside([string]$Path, [string]$Parent) {
    if (-not $Path -or -not $Parent) { return $false }
    $Full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $Base = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    return [string]::Equals($Full, $Base, [StringComparison]::OrdinalIgnoreCase) -or $Full.StartsWith($Base + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-SafeDestination {
    if (-not $PortableParent -or -not $PortableName -or $PortableRoot -eq [IO.Path]::GetPathRoot($PortableRoot).TrimEnd('\')) { throw 'Choose a dedicated app subfolder, not a drive root.' }
    $UserRoot = [Environment]::GetFolderPath('UserProfile')
    foreach ($Root in @($UserRoot, $Desktop, $Documents, $LocalRoot)) {
        if ($Root -and (Test-Inside $Root $PortableRoot)) { throw 'Choose a dedicated app subfolder, not a whole user or known folder.' }
    }
    foreach ($SystemRoot in @($env:WINDIR, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData)) {
        if ($SystemRoot -and (Test-Inside $PortableRoot $SystemRoot)) { throw "A portable app cannot replace a protected system folder: $PortableRoot" }
    }
    if ((Test-Inside $PortableRoot $ProjectRoot) -or (Test-Inside $ProjectRoot $PortableRoot)) { throw 'Keep the portable app outside the development project and its parent folders.' }
    if ((Test-Inside $BuildDirectory $PortableRoot) -or (Test-Inside $PortableRoot $BuildDirectory)) { throw 'The portable destination and build directory must be separate.' }
}

function Assert-SafeDataOrigin([string]$Path) {
    $Full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($Full -eq [IO.Path]::GetPathRoot($Full).TrimEnd('\') -or (Test-Inside $ProjectRoot $Full) -or (Test-Inside $BuildDirectory $Full) -or (Test-Inside $PortableRoot $Full)) { throw 'Choose the dedicated Hisser data folder, not a parent/project/app folder.' }
    foreach ($Root in @([Environment]::GetFolderPath('UserProfile'), $Desktop, $Documents, $LocalRoot)) {
        if ($Root -and (Test-Inside $Root $Full)) { throw 'A complete user or known folder cannot be moved as app data.' }
    }
    foreach ($SystemRoot in @($env:WINDIR, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData)) {
        if ($SystemRoot -and (Test-Inside $Full $SystemRoot)) { throw 'System folders cannot be moved as app data.' }
    }
    Assert-NoReparse $Full -Tree
}

function Assert-NoReparse([string]$Path, [switch]$Tree) {
    $Current = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    while ($Current) {
        if (Test-Path -LiteralPath $Current) {
            $Item = Get-Item -LiteralPath $Current -Force
            if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Refusing to modify a linked path: $Current" }
        }
        $Parent = Split-Path -Path $Current -Parent
        if ($Parent -eq $Current) { break }
        $Current = $Parent
    }
    if ($Tree -and (Test-Path -LiteralPath $Path -PathType Container)) {
        $Links = @(Get-ChildItem -LiteralPath $Path -Recurse -Force | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 })
        if ($Links.Count -gt 0) { throw "The folder contains a linked file or directory: $($Links[0].FullName)" }
    }
}

function Assert-PortablePath([string]$Path) {
    $Full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not [string]::Equals((Split-Path $Full -Parent), $PortableParent, [StringComparison]::OrdinalIgnoreCase)) { throw "Portable operation escaped the approved destination parent: $Full" }
    $Name = Split-Path $Full -Leaf
    $TemporaryPattern = '^' + [regex]::Escape($PortableName) + '\.(preparing|previous)-[a-f0-9]{32}$'
    if ($Name -ne $PortableName -and $Name -notmatch $TemporaryPattern) { throw "Portable operation targets an unrecognized folder: $Full" }
    Assert-NoReparse $Full -Tree
}

function Remove-PortableFolder([string]$Path) {
    Assert-PortablePath $Path
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

function Assert-NotRunning {
    $Processes = @(Get-CimInstance Win32_Process -Filter "Name='Hisser.exe' OR Name='whisper-cli.exe' OR Name='ffmpeg.exe' OR Name='ffprobe.exe'")
    foreach ($Process in $Processes) {
        $ExePath = [string]$Process.ExecutablePath
        $Command = [string]$Process.CommandLine
        if ($ExePath -and ($ExePath.StartsWith($PortableRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $ExePath.StartsWith($StageRoot + '\', [StringComparison]::OrdinalIgnoreCase))) { throw 'Close Hisser and wait for its transcription to stop before updating its portable folder.' }
        if ($Process.Name -eq 'whisper-cli.exe' -and $Command.IndexOf($LegacyData + '\', [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'The setup model is still in use. Wait for that job to finish before packaging.' }
        if ($DataOrigin -and $Process.Name -eq 'whisper-cli.exe' -and $Command.IndexOf($DataOrigin + '\', [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'The selected model is still in use. Wait for that job to finish before packaging.' }
        if (-not $ExePath -and $Process.Name -eq 'Hisser.exe') { throw 'Windows could not confirm whether Hisser is open. Close it and retry.' }
    }
}

function Test-Package([string]$Folder) {
    foreach ($Relative in @('Hisser.exe', '_internal\assets\hisser.ico', '_internal\runtime\whisper-cli.exe', '_internal\runtime\ffmpeg.exe', '_internal\runtime\ffprobe.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Folder $Relative) -PathType Leaf)) { throw "The package is missing $Relative. Rebuild Hisser." }
    }
}

function Invoke-PackageCheck([string]$Folder) {
    $ReportPath = Join-Path $Folder '.portable-self-test.json'
    if (Test-Path -LiteralPath $ReportPath) { Remove-Item -LiteralPath $ReportPath -Force }
    $Process = Start-Process -FilePath (Join-Path $Folder 'Hisser.exe') -ArgumentList @('--self-test', ('"' + $ReportPath + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) { throw 'The portable application failed startup. The prior folder/model will be restored.' }
    $Result = Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $Result.runtime_files -or -not $Result.tk -or -not $Result.model -or -not $Result.exports -or -not $Result.portable) { throw 'The portable application could not verify Tk, runtime, model, exports and portable mode.' }
    $ExpectedData = [IO.Path]::GetFullPath((Join-Path $Folder 'data')).TrimEnd('\')
    if (-not [string]::Equals([string]$Result.data_root, $ExpectedData, [StringComparison]::OrdinalIgnoreCase)) { throw 'The application is using data outside its portable folder. Deployment stopped.' }
    return $Result
}

Assert-SafeDestination
Assert-NoReparse $PortableParent
Assert-NoReparse $Desktop
Assert-NoReparse $DesktopShortcut
Assert-PortablePath $PortableRoot
Assert-PortablePath $StageRoot
Assert-PortablePath $BackupRoot
Assert-NoReparse $BuildDirectory -Tree
Assert-NoReparse $LegacyData -Tree
Test-Package $BuildDirectory
Assert-NotRunning
if (Test-Path -LiteralPath (Join-Path $BuildDirectory 'data')) { throw 'The build package must not contain a second model/data copy.' }
if (Test-Path -LiteralPath $PortableRoot) {
    $Marker = Join-Path $PortableRoot 'portable.json'
    if (-not (Test-Path -LiteralPath $Marker -PathType Leaf)) { throw 'The destination folder already exists without the portable marker. It was left untouched.' }
    $Existing = Get-Content -LiteralPath $Marker -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Existing.application_id -ne $ApplicationId) { throw 'The existing Hisser folder is unrecognized. It was left untouched.' }
    $Known = @('_internal', 'Hisser.exe', 'build-manifest.json', 'portable.json', '.portable-self-test.json', 'USER_GUIDE.md', 'data')
    $Unknown = @(Get-ChildItem -LiteralPath $PortableRoot -Force | Where-Object { $_.Name -notin $Known })
    if ($Unknown.Count -gt 0) { throw "Extra files exist at the app root; move them outside Hisser before updating: $($Unknown.Name -join ', ')" }
    if (Test-Path -LiteralPath (Join-Path $PortableRoot 'data') -PathType Container) { $DataOrigin = Join-Path $PortableRoot 'data' }
}
if ($DataDirectory) {
    $RequestedData = [IO.Path]::GetFullPath($DataDirectory).TrimEnd('\')
    if ($DataOrigin -and -not [string]::Equals($DataOrigin, $RequestedData, [StringComparison]::OrdinalIgnoreCase)) { throw 'The destination already has its own data. Resolve the two data folders before packaging.' }
    $DataOrigin = $RequestedData
} elseif (Test-Path -LiteralPath $LegacyData) {
    if ($DataOrigin) { throw 'Both portable and setup data exist. Select one explicitly with -DataDirectory; nothing was changed.' }
    $DataOrigin = $LegacyData
}
if (-not $DataOrigin) { throw 'The verified model/data folder is missing. Restore it before packaging.' }
Assert-SafeDataOrigin $DataOrigin
$ModelPath = Join-Path $DataOrigin 'models\ggml-large-v3-q5_0.bin'
$MetadataPath = $ModelPath + '.metadata.json'
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf) -or -not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) { throw 'The model or its verification metadata is missing.' }
$Metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ((Get-Item -LiteralPath $ModelPath).Length -ne $Metadata.size -or (Get-FileHash -LiteralPath $ModelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Metadata.sha256) { throw 'The model does not match its upstream verification record.' }
Assert-NotRunning
if (-not $PSCmdlet.ShouldProcess($PortableRoot, 'Stage and verify the app, move the single model/data directory, and create the Hisser desktop shortcut')) { return }

try {
    if (-not (Test-Path -LiteralPath $PortableParent)) { New-Item -ItemType Directory -Path $PortableParent -Force | Out-Null }
    New-Item -ItemType Directory -Path $StageRoot | Out-Null
    foreach ($Item in (Get-ChildItem -LiteralPath $BuildDirectory -Force)) { Copy-Item -LiteralPath $Item.FullName -Destination $StageRoot -Recurse -Force }
    $Guide = Join-Path $ProjectRoot 'USER_GUIDE.md'
    if (Test-Path -LiteralPath $Guide -PathType Leaf) { Copy-Item -LiteralPath $Guide -Destination (Join-Path $StageRoot 'USER_GUIDE.md') }
    $MarkerText = [ordered]@{ application_id = $ApplicationId; name = 'Hisser'; version = '1.0.0'; portable = $true; data_relative_path = 'data'; created_utc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $StageRoot 'portable.json'), $MarkerText + "`n", [Text.UTF8Encoding]::new($false))
    Test-Package $StageRoot
    Assert-NotRunning
    # Same-volume move of the single model/data folder, not a duplicate download.
    Assert-NoReparse $DataOrigin -Tree
    Move-Item -LiteralPath $DataOrigin -Destination (Join-Path $StageRoot 'data')
    $DataMoved = $true
    $null = Invoke-PackageCheck $StageRoot
    if (Test-Path -LiteralPath $PortableRoot) {
        Assert-PortablePath $PortableRoot
        Assert-PortablePath $BackupRoot
        Move-Item -LiteralPath $PortableRoot -Destination $BackupRoot
        $OldMoved = $true
    }
    Assert-PortablePath $StageRoot
    Assert-PortablePath $PortableRoot
    Move-Item -LiteralPath $StageRoot -Destination $PortableRoot
    $NewMoved = $true
    $SelfTest = Invoke-PackageCheck $PortableRoot
    $Shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $DesktopShortcut) {
        if (-not (Test-Path -LiteralPath $DesktopShortcut -PathType Leaf)) { throw 'A directory occupies the Hisser desktop shortcut path.' }
        Assert-NoReparse $DesktopShortcut
        $PriorLink = $Shell.CreateShortcut($DesktopShortcut)
        if (-not [string]::Equals($PriorLink.TargetPath, (Join-Path $PortableRoot 'Hisser.exe'), [StringComparison]::OrdinalIgnoreCase)) {
            $PriorFolder = Split-Path -Path $PriorLink.TargetPath -Parent
            $PriorMarker = Join-Path $PriorFolder 'portable.json'
            if ((Split-Path -Path $PriorLink.TargetPath -Leaf) -ne 'Hisser.exe' -or -not (Test-Path -LiteralPath $PriorMarker -PathType Leaf)) { throw 'An unrelated Hisser desktop shortcut exists; it was left untouched.' }
            Assert-NoReparse $PriorMarker
            $PriorApp = Get-Content -LiteralPath $PriorMarker -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($PriorApp.application_id -ne $ApplicationId) { throw 'An unrelated Hisser desktop shortcut exists; it was left untouched.' }
        }
        $ShortcutBefore = [IO.File]::ReadAllBytes($DesktopShortcut)
    }
    $ShortcutTouched = $true
    $Link = $Shell.CreateShortcut($DesktopShortcut)
    $Link.TargetPath = Join-Path $PortableRoot 'Hisser.exe'
    $Link.Arguments = ''
    $Link.WorkingDirectory = $PortableRoot
    $Link.IconLocation = (Join-Path $PortableRoot 'Hisser.exe') + ',0'
    $Link.Description = 'Hisser - local audio and video transcription'
    $Link.Save()
    $Record = [ordered]@{
        application_id = $ApplicationId
        portable = $true
        deployed_utc = [DateTime]::UtcNow.ToString('o')
        folder = $PortableRoot
        executable = (Join-Path $PortableRoot 'Hisser.exe')
        data_directory = (Join-Path $PortableRoot 'data')
        bytes = [long](Get-ChildItem -LiteralPath $PortableRoot -File -Recurse | Measure-Object Length -Sum).Sum
        model_copied = $false
        model_moved_from = $DataOrigin
        model_sha256 = $Metadata.sha256
        external_registration_created = $false
        external_shortcuts_created = $true
        desktop_shortcut = $DesktopShortcut
        source_project_preserved = $true
        self_test = $SelfTest
    }
    $QaRoot = Join-Path $ProjectRoot 'qa'
    New-Item -ItemType Directory -Path $QaRoot -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $QaRoot 'portable-deployment.json'), ($Record | ConvertTo-Json -Depth 8) + "`n", [Text.UTF8Encoding]::new($false))
    $Committed = $true
} catch {
    $OriginalError = $_
    try {
        if ($ShortcutTouched) {
            Assert-NoReparse $DesktopShortcut
            if ($null -ne $ShortcutBefore) { [IO.File]::WriteAllBytes($DesktopShortcut, [byte[]]$ShortcutBefore) }
            elseif (Test-Path -LiteralPath $DesktopShortcut -PathType Leaf) { Remove-Item -LiteralPath $DesktopShortcut -Force }
        }
        $CurrentRoot = if ($NewMoved) { $PortableRoot } else { $StageRoot }
        $CurrentData = Join-Path $CurrentRoot 'data'
        $RestoreData = $DataOrigin
        if ($OldMoved -and $DataOrigin.StartsWith($PortableRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { $RestoreData = Join-Path $BackupRoot 'data' }
        if ($DataMoved -and (Test-Path -LiteralPath $CurrentData)) {
            Assert-PortablePath $CurrentRoot
            Assert-NoReparse $RestoreData -Tree
            if (Test-Path -LiteralPath $RestoreData) { throw "Rollback target already exists; model preserved at $CurrentData" }
            Move-Item -LiteralPath $CurrentData -Destination $RestoreData
        }
        if ($NewMoved) { Remove-PortableFolder $PortableRoot }
        if ($OldMoved -and (Test-Path -LiteralPath $BackupRoot)) {
            Assert-PortablePath $BackupRoot
            Assert-PortablePath $PortableRoot
            Move-Item -LiteralPath $BackupRoot -Destination $PortableRoot
        }
        if (Test-Path -LiteralPath $StageRoot) { Remove-PortableFolder $StageRoot }
    } catch { Write-Warning "Rollback needs attention: $($_.Exception.Message). Staged/backup folders were preserved to protect the model." }
    throw $OriginalError
}
if ($Committed -and (Test-Path -LiteralPath $BackupRoot)) { Remove-PortableFolder $BackupRoot }
Write-Host "Ready: $(Join-Path $PortableRoot 'Hisser.exe')"
Write-Host 'All app data is inside this folder. Close Hisser, delete this folder and remove the Hisser desktop shortcut to remove the app.'
Write-Host ('Desktop shortcut: ' + $DesktopShortcut)
Write-Host 'No Windows installation, registry entry or Start menu item was created.'

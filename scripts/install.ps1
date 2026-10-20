[CmdletBinding(SupportsShouldProcess = $true)]
param([string]$BuildDirectory = '', [string]$Destination = '', [string]$DataDirectory = '')

# Compatibility entry point: portable folder plus a desktop shortcut only.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'package-portable.ps1') -BuildDirectory $BuildDirectory -Destination $Destination -DataDirectory $DataDirectory -WhatIf:$WhatIfPreference

param(
    [string]$SourceDir = (Join-Path $PSScriptRoot "tmsforkorea"),
    # QGIS 프로필: ...\python\plugins (이름 tmsforkorea로 복사)
    [string]$PluginsDir = (Split-Path $PSScriptRoot -Parent),
    [string]$PluginName = "tmsforkorea",
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"

$targetDir = Join-Path $PluginsDir $PluginName

if (-not (Test-Path $SourceDir)) {
    throw "Source directory not found: $SourceDir"
}

if ($targetDir.TrimEnd('\') -ieq $SourceDir.TrimEnd('\')) {
    throw "Source and target are the same path. Aborting."
}

Write-Host "== TMS for Korea Builder =="
Write-Host "Source : $SourceDir"
Write-Host "Target : $targetDir"

if ((Test-Path $targetDir) -and (-not $NoClean)) {
    Write-Host "Cleaning existing target..."
    Remove-Item -Path $targetDir -Recurse -Force
}

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir | Out-Null
}

$excludeDirs = @("__pycache__", ".git", ".idea", ".vscode")
$excludeExts = @(".pyc", ".pyo")

Get-ChildItem -Path $SourceDir -Recurse -Force | ForEach-Object {
    $fullPath = $_.FullName
    $relativePath = $fullPath.Substring($SourceDir.Length).TrimStart('\')

    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        return
    }

    foreach ($dirName in $excludeDirs) {
        if ($relativePath -match "(^|\\)$([Regex]::Escape($dirName))(\\|$)") {
            return
        }
    }

    if (-not $_.PSIsContainer) {
        $ext = [System.IO.Path]::GetExtension($_.Name)
        if ($excludeExts -contains $ext) {
            return
        }
    }

    $destPath = Join-Path $targetDir $relativePath

    if ($_.PSIsContainer) {
        if (-not (Test-Path $destPath)) {
            New-Item -ItemType Directory -Path $destPath | Out-Null
        }
    } else {
        $destParent = Split-Path $destPath -Parent
        if (-not (Test-Path $destParent)) {
            New-Item -ItemType Directory -Path $destParent | Out-Null
        }
        Copy-Item -Path $fullPath -Destination $destPath -Force
    }
}

Write-Host "Build complete."
Write-Host "QGIS plugin folder ready: $targetDir"

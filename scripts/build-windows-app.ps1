param(
    [string]$OutputRoot = "D:\Codex\Builds\Hamiltonian",
    [string]$DataRoot = "D:\Codex\Data\Hamiltonian",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$EnvironmentRoot = Join-Path $OutputRoot "environment"
$TempRoot = Join-Path $OutputRoot "temp"
$PipCache = Join-Path $OutputRoot "pip-cache"
$PyInstallerConfig = Join-Path $OutputRoot "pyinstaller-config"
$DistRoot = Join-Path $OutputRoot "dist"
$WorkRoot = Join-Path $OutputRoot "work"
$SpecRoot = Join-Path $OutputRoot "spec"
$AssetRoot = Join-Path $OutputRoot "assets"
$IconPath = Join-Path $AssetRoot "Hamiltonian.ico"

New-Item -ItemType Directory -Force -Path $OutputRoot, $TempRoot, $PipCache, $PyInstallerConfig, $DistRoot, $WorkRoot, $SpecRoot, $AssetRoot | Out-Null
$env:TEMP = $TempRoot
$env:TMP = $TempRoot
$env:PIP_CACHE_DIR = $PipCache
$env:PYINSTALLER_CONFIG_DIR = $PyInstallerConfig

Add-Type -AssemblyName System.Drawing
$bitmap = [System.Drawing.Bitmap]::new(256, 256)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.ColorTranslator]::FromHtml("#080A0D"))
$borderPen = [System.Drawing.Pen]::new([System.Drawing.ColorTranslator]::FromHtml("#3A2418"), 6)
$markPen = [System.Drawing.Pen]::new([System.Drawing.ColorTranslator]::FromHtml("#FF6400"), 20)
$markPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Square
$markPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Square
$graphics.DrawRectangle($borderPen, 25, 25, 206, 206)
$graphics.DrawLine($markPen, 78, 70, 78, 186)
$graphics.DrawLine($markPen, 178, 70, 178, 186)
$graphics.DrawLine($markPen, 78, 128, 178, 128)
$graphics.DrawLine($markPen, 50, 62, 50, 92)
$graphics.DrawLine($markPen, 50, 62, 66, 62)
$graphics.DrawLine($markPen, 206, 164, 206, 194)
$graphics.DrawLine($markPen, 190, 194, 206, 194)
$pngPath = Join-Path $AssetRoot "Hamiltonian.png"
$bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)
$markPen.Dispose()
$borderPen.Dispose()
$graphics.Dispose()
$bitmap.Dispose()

$pngBytes = [System.IO.File]::ReadAllBytes($pngPath)
$iconStream = [System.IO.File]::Open($IconPath, [System.IO.FileMode]::Create)
$iconWriter = [System.IO.BinaryWriter]::new($iconStream)
$iconWriter.Write([UInt16]0)
$iconWriter.Write([UInt16]1)
$iconWriter.Write([UInt16]1)
$iconWriter.Write([Byte]0)
$iconWriter.Write([Byte]0)
$iconWriter.Write([Byte]0)
$iconWriter.Write([Byte]0)
$iconWriter.Write([UInt16]1)
$iconWriter.Write([UInt16]32)
$iconWriter.Write([UInt32]$pngBytes.Length)
$iconWriter.Write([UInt32]22)
$iconWriter.Write($pngBytes)
$iconWriter.Dispose()
$iconStream.Dispose()

if (-not (Test-Path (Join-Path $EnvironmentRoot "Scripts\python.exe"))) {
    python -m venv $EnvironmentRoot
}

$Python = Join-Path $EnvironmentRoot "Scripts\python.exe"
if (-not $SkipInstall) {
    & $Python -m pip install --disable-pip-version-check --upgrade pip
    & $Python -m pip install --disable-pip-version-check -e "${ProjectRoot}[desktop,build]"
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name Hamiltonian `
    --icon $IconPath `
    --paths (Join-Path $ProjectRoot "src") `
    --collect-all webview `
    --collect-data hamiltonian `
    --distpath $DistRoot `
    --workpath $WorkRoot `
    --specpath $SpecRoot `
    (Join-Path $PSScriptRoot "run-desktop.py")

$Executable = Join-Path $DistRoot "Hamiltonian\Hamiltonian.exe"
if (-not (Test-Path $Executable)) {
    throw "Hamiltonian desktop build did not produce $Executable"
}

$Version = (& $Python -c "import hamiltonian; print(hamiltonian.__version__)").Trim()
$ExecutableInfo = Get-Item $Executable
$ExecutableHash = (Get-FileHash $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
$BuildInfoPath = Join-Path $ExecutableInfo.DirectoryName "build-info.json"
$ChecksumPath = Join-Path $ExecutableInfo.DirectoryName "SHA256SUMS.txt"
$BuildInfo = [ordered]@{
    schema = "hamiltonian.desktop-build.v1"
    version = $Version
    built_at = [DateTime]::UtcNow.ToString("o")
    package = "windows-portable-onedir"
    executable = "Hamiltonian.exe"
    executable_size = $ExecutableInfo.Length
    executable_sha256 = $ExecutableHash
    update_policy = "manual-local-package"
    remote_update = $false
    signed = $false
}
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $BuildInfoPath,
    ($BuildInfo | ConvertTo-Json -Depth 4) + [Environment]::NewLine,
    $Utf8NoBom
)
[System.IO.File]::WriteAllText(
    $ChecksumPath,
    "$ExecutableHash  Hamiltonian.exe$([Environment]::NewLine)",
    $Utf8NoBom
)

$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
$ShortcutPath = Join-Path $OutputRoot "Hamiltonian.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Executable
$Shortcut.Arguments = "--data-dir `"$DataRoot`""
$Shortcut.WorkingDirectory = $ExecutableInfo.DirectoryName
$Shortcut.IconLocation = "$Executable,0"
$Shortcut.Description = "Hamiltonian local agent operations"
$Shortcut.Save()

Write-Output "Hamiltonian desktop build: $Executable"
Write-Output "Build manifest: $BuildInfoPath"
Write-Output "D-drive shortcut: $ShortcutPath"

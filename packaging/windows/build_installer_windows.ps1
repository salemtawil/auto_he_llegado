$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SpecPath = Join-Path $PSScriptRoot "auto_he_llegado.spec"
$InstallerScriptPath = Join-Path $PSScriptRoot "installer\auto_he_llegado.iss"
$BuildRoot = Join-Path $ProjectRoot "build\installer_windows"
$DistRoot = Join-Path $ProjectRoot "dist"
$DistAppRoot = Join-Path $DistRoot "AutoHeLlegado"
$ReleasesRoot = Join-Path $ProjectRoot "releases"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$SetupPath = Join-Path $ReleasesRoot "AutoHeLlegado_Setup_$Timestamp.exe"
$UpdateZipPath = Join-Path $ReleasesRoot "AutoHeLlegado_Update_$Timestamp.zip"
$MsPlaywrightSource = Join-Path $env:USERPROFILE "AppData\Local\ms-playwright"
$EnvPath = Join-Path $ProjectRoot ".env"
$EnvExamplePath = Join-Path $ProjectRoot ".env.example"
$UpdaterConfigPath = Join-Path $ProjectRoot "updater\updater_config.json"

function Get-PythonExe {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

function Get-InnoSetupExe {
    $command = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $commonPaths = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $commonPaths) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "No se encontro ISCC.exe de Inno Setup. Instala Inno Setup 6 o agrega iscc.exe al PATH."
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Script
    )
    Write-Host ""
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Script
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )
    $pythonExe = Get-PythonExe
    & $pythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo comando Python: $pythonExe $($Arguments -join ' ')"
    }
}

function Remove-PathIfExists {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if (Test-Path $PathValue) {
        Remove-Item -LiteralPath $PathValue -Recurse -Force
    }
}

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if (-not (Test-Path $PathValue)) {
        New-Item -ItemType Directory -Path $PathValue | Out-Null
    }
}

function Assert-PathExists {
    param(
        [Parameter(Mandatory = $true)][string]$PathValue,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not (Test-Path $PathValue)) {
        throw $Message
    }
}

function Assert-InternalEnvExists {
    if (-not (Test-Path $EnvPath)) {
        throw "No se encontró .env en la raíz del proyecto. Este instalador interno requiere .env para Supabase. Crea .env antes de construir. No se imprimen secretos."
    }
}

function Assert-UpdaterConfigIsUsable {
    param([Parameter(Mandatory = $true)][string]$PathValue)

    Assert-PathExists -PathValue $PathValue -Message "No se encontro updater\updater_config.json. Configura el updater antes de construir el instalador."
    $config = Get-Content $PathValue -Raw | ConvertFrom-Json
    $owner = [string]$config.owner
    $repo = [string]$config.repo
    $branch = [string]$config.branch

    if ([string]::IsNullOrWhiteSpace($owner) -or [string]::IsNullOrWhiteSpace($repo) -or [string]::IsNullOrWhiteSpace($branch)) {
        throw "updater\updater_config.json es invalido. owner, repo y branch son obligatorios."
    }
    if ($owner -eq "TU_USUARIO" -or $repo -eq "TU_REPO") {
        throw "updater\updater_config.json contiene placeholders. Configura owner/repo reales antes de construir el instalador."
    }
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    Assert-PathExists -PathValue $SourcePath -Message "No se encontro la carpeta requerida: $SourcePath"
    Remove-PathIfExists -PathValue $TargetPath
    Copy-Item -Path $SourcePath -Destination $TargetPath -Recurse -Force
}

function Copy-UpdaterFilesForInstaller {
    $updaterSourceDir = Join-Path $ProjectRoot "updater"
    $updaterTargetDir = Join-Path $DistAppRoot "updater"
    Ensure-Directory -PathValue $updaterTargetDir

    $updaterFiles = @(
        "apply_update_helper.py",
        "github_sync_updater.py",
        "README.md",
        "updater_config.example.json",
        "updater_config.json",
        "update_config.json",
        "update_latest.example.json"
    )

    foreach ($fileName in $updaterFiles) {
        $sourcePath = Join-Path $updaterSourceDir $fileName
        Assert-PathExists -PathValue $sourcePath -Message "Falta updater\$fileName"
        Copy-Item -Path $sourcePath -Destination (Join-Path $updaterTargetDir $fileName) -Force
    }

    Copy-DirectoryContents -SourcePath (Join-Path $updaterSourceDir "launchers") -TargetPath (Join-Path $updaterTargetDir "launchers")
}

function Initialize-InstallerRuntimeDirectories {
    $runtimeDirs = @(
        "logs",
        "exports",
        "updates",
        "updates\backups",
        "updates\update_logs",
        "updates\staging",
        "local_data",
        "local_data\config",
        "local_data\logs",
        "local_data\debug",
        "local_data\results",
        "local_data\results\screenshots",
        "local_data\failed_uploads",
        "local_data\temp_photos",
        "chrome_profiles"
    )
    foreach ($relativeDir in $runtimeDirs) {
        Ensure-Directory -PathValue (Join-Path $DistAppRoot $relativeDir)
    }
}

function Copy-MsPlaywrightForInstaller {
    Copy-DirectoryContents -SourcePath $MsPlaywrightSource -TargetPath (Join-Path $DistAppRoot "ms-playwright")
}

function New-UpdatePackageZip {
    param(
        [Parameter(Mandatory = $true)][string]$DestinationZipPath,
        [Parameter(Mandatory = $true)][string]$StageRoot
    )

    Remove-PathIfExists -PathValue $StageRoot
    Ensure-Directory -PathValue $StageRoot

    $rootFiles = @(
        "AutoHeLlegado.exe",
        "AutoHeLlegadoUploader.exe",
        "AutoHeLlegadoDebugInspector.exe",
        "AutoHeLlegadoUpdateHelper.exe",
        ".env.example"
    )
    foreach ($fileName in $rootFiles) {
        $sourcePath = Join-Path $DistAppRoot $fileName
        Assert-PathExists -PathValue $sourcePath -Message "Falta dist\AutoHeLlegado\$fileName"
        Copy-Item -Path $sourcePath -Destination (Join-Path $StageRoot $fileName) -Force
    }

    $directoriesToCopy = @(
        "_internal",
        "updater",
        "browser_extension"
    )
    foreach ($directoryName in $directoriesToCopy) {
        Copy-DirectoryContents -SourcePath (Join-Path $DistAppRoot $directoryName) -TargetPath (Join-Path $StageRoot $directoryName)
    }

    $excludedPaths = @(
        (Join-Path $StageRoot ".env"),
        (Join-Path $StageRoot "updater\updater_config.json")
    )
    foreach ($excludedPath in $excludedPaths) {
        if (Test-Path $excludedPath) {
            Remove-Item -LiteralPath $excludedPath -Force
        }
    }

    if (Test-Path $DestinationZipPath) {
        Remove-Item -LiteralPath $DestinationZipPath -Force
    }

    Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $DestinationZipPath -CompressionLevel Optimal
}

Push-Location $ProjectRoot
try {
    Invoke-Step -Label "Validando precondiciones del instalador" -Script {
        Assert-InternalEnvExists
        Assert-PathExists -PathValue $EnvExamplePath -Message "No se encontro .env.example en la raiz del proyecto."
        Assert-UpdaterConfigIsUsable -PathValue $UpdaterConfigPath
        Assert-PathExists -PathValue $InstallerScriptPath -Message "No se encontro packaging\windows\installer\auto_he_llegado.iss"
    }

    Invoke-Step -Label "Validando tests previos" -Script {
        Invoke-Python -Arguments @("-m", "pytest", "tests", "-q")
    }

    Invoke-Step -Label "Compilando archivos Python clave" -Script {
        Invoke-Python -Arguments @("-m", "py_compile", "app_main.py")
        Invoke-Python -Arguments @("-m", "py_compile", "app_uploader.py")
        Invoke-Python -Arguments @("-m", "py_compile", "app_debug_inspector.py")
        Invoke-Python -Arguments @("-m", "py_compile", "app_update_helper.py")
        Invoke-Python -Arguments @("-m", "py_compile", "updater\apply_update_helper.py")
        Invoke-Python -Arguments @("-m", "py_compile", "ui\main_app\window.py")
    }

    Invoke-Step -Label "Limpiando salidas anteriores del instalador" -Script {
        Remove-PathIfExists -PathValue $BuildRoot
        Remove-PathIfExists -PathValue $DistAppRoot
        Ensure-Directory -PathValue $BuildRoot
        Ensure-Directory -PathValue $DistRoot
        Ensure-Directory -PathValue $ReleasesRoot
    }

    Invoke-Step -Label "Verificando PyInstaller e Inno Setup" -Script {
        Invoke-Python -Arguments @("-m", "PyInstaller", "--version")
        $null = Get-InnoSetupExe
    }

    Invoke-Step -Label "Verificando cache local de ms-playwright" -Script {
        Assert-PathExists -PathValue $MsPlaywrightSource -Message "No se encontro ms-playwright en $MsPlaywrightSource. BrowserManager lo requiere para el instalador."
    }

    Invoke-Step -Label "Generando build base con PyInstaller" -Script {
        Invoke-Python -Arguments @(
            "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath", $DistRoot,
            "--workpath", $BuildRoot,
            $SpecPath
        )
    }

    Invoke-Step -Label "Preparando layout instalable" -Script {
        Copy-UpdaterFilesForInstaller
        Copy-DirectoryContents -SourcePath (Join-Path $ProjectRoot "browser_extension") -TargetPath (Join-Path $DistAppRoot "browser_extension")
        Copy-MsPlaywrightForInstaller
        Copy-Item -Path $EnvPath -Destination (Join-Path $DistAppRoot ".env") -Force
        Copy-Item -Path $EnvExamplePath -Destination (Join-Path $DistAppRoot ".env.example") -Force
        Initialize-InstallerRuntimeDirectories
    }

    Invoke-Step -Label "Generando update zip del build" -Script {
        $updateStageRoot = Join-Path $BuildRoot "update_payload"
        New-UpdatePackageZip -DestinationZipPath $UpdateZipPath -StageRoot $updateStageRoot
    }

    Invoke-Step -Label "Construyendo instalador con Inno Setup" -Script {
        $isccExe = Get-InnoSetupExe
        & $isccExe `
            "/DDistAppDir=$DistAppRoot" `
            "/DOutputDir=$ReleasesRoot" `
            "/DOutputBaseFilename=AutoHeLlegado_Setup_$Timestamp" `
            "/DAppVersion=$Timestamp" `
            $InstallerScriptPath
        if ($LASTEXITCODE -ne 0) {
            throw "Fallo Inno Setup al generar el instalador."
        }
    }

    Invoke-Step -Label "Validando artefactos finales" -Script {
        Assert-PathExists -PathValue (Join-Path $DistAppRoot "AutoHeLlegado.exe") -Message "Falta dist\AutoHeLlegado\AutoHeLlegado.exe"
        Assert-PathExists -PathValue (Join-Path $DistAppRoot "AutoHeLlegadoUpdateHelper.exe") -Message "Falta dist\AutoHeLlegado\AutoHeLlegadoUpdateHelper.exe"
        Assert-PathExists -PathValue (Join-Path $DistAppRoot "_internal") -Message "Falta dist\AutoHeLlegado\_internal\"
        Assert-PathExists -PathValue (Join-Path $DistAppRoot "updater") -Message "Falta dist\AutoHeLlegado\updater\"
        Assert-PathExists -PathValue (Join-Path $DistAppRoot "browser_extension") -Message "Falta dist\AutoHeLlegado\browser_extension\"
        Assert-PathExists -PathValue (Join-Path $DistAppRoot "ms-playwright") -Message "Falta dist\AutoHeLlegado\ms-playwright\"
        Assert-PathExists -PathValue (Join-Path $DistAppRoot ".env") -Message "Falta dist\AutoHeLlegado\.env"
        Assert-PathExists -PathValue (Join-Path $DistAppRoot ".env.example") -Message "Falta dist\AutoHeLlegado\.env.example"
        Assert-PathExists -PathValue $SetupPath -Message "No se genero releases\AutoHeLlegado_Setup_$Timestamp.exe"
        Assert-PathExists -PathValue $UpdateZipPath -Message "No se genero releases\AutoHeLlegado_Update_$Timestamp.zip"
    }

    Write-Host ""
    Write-Host "Instalador generado:" -ForegroundColor Green
    Write-Host "  $SetupPath"
    Write-Host "Update zip generado:" -ForegroundColor Green
    Write-Host "  $UpdateZipPath"
}
finally {
    Pop-Location
}

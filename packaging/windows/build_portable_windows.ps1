$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SpecPath = Join-Path $PSScriptRoot "auto_he_llegado.spec"
$BuildRoot = Join-Path $ProjectRoot "build\portable_windows"
$DistRoot = Join-Path $ProjectRoot "dist"
$PortableRoot = Join-Path $DistRoot "AutoHeLlegado"
$ReleasesRoot = Join-Path $ProjectRoot "releases"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ZipPath = Join-Path $ReleasesRoot "AutoHeLlegado_Windows_Portable_$Timestamp.zip"
$MsPlaywrightSource = Join-Path $env:USERPROFILE "AppData\Local\ms-playwright"

function Get-PythonExe {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
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

function Copy-PortableAssetFromInternal {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    $source = Join-Path $PortableRoot "_internal\$RelativePath"
    $target = Join-Path $PortableRoot $RelativePath
    Assert-PathExists -PathValue $source -Message "Falta recurso empaquetado en _internal: $RelativePath"
    Remove-PathIfExists -PathValue $target
    Copy-Item -Path $source -Destination $target -Recurse -Force
}

function Test-UpdaterConfigIsPublicCandidate {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if (-not (Test-Path $PathValue)) {
        return $false
    }

    $config = Get-Content $PathValue -Raw | ConvertFrom-Json
    $owner = [string]$config.owner
    $repo = [string]$config.repo
    $branch = [string]$config.branch
    if ([string]::IsNullOrWhiteSpace($owner) -or [string]::IsNullOrWhiteSpace($repo) -or [string]::IsNullOrWhiteSpace($branch)) {
        return $false
    }
    if ($owner -eq "TU_USUARIO" -or $repo -eq "TU_REPO") {
        return $false
    }
    return $true
}

function Write-PortableUpdaterConfig {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    $config = Get-Content $SourcePath -Raw | ConvertFrom-Json
    $config.app_entrypoints = @(
        "AutoHeLlegado.exe",
        "AutoHeLlegadoUploader.exe",
        "AutoHeLlegadoDebugInspector.exe"
    )
    $config | ConvertTo-Json -Depth 10 | Set-Content -Path $TargetPath -Encoding UTF8
}

Push-Location $ProjectRoot
try {
    Invoke-Step -Label "Validando tests previos" -Script {
        Invoke-Python -Arguments @("-m", "pytest", "tests", "-q")
    }

    Invoke-Step -Label "Compilando archivos Python clave" -Script {
        Invoke-Python -Arguments @("-m", "py_compile", "app_main.py")
        Invoke-Python -Arguments @("-m", "py_compile", "app_uploader.py")
        Invoke-Python -Arguments @("-m", "py_compile", "app_debug_inspector.py")
        Invoke-Python -Arguments @("-m", "py_compile", "app_update_helper.py")
        Invoke-Python -Arguments @("-m", "py_compile", "updater\github_sync_updater.py")
        Invoke-Python -Arguments @("-m", "py_compile", "updater\apply_update_helper.py")
        Invoke-Python -Arguments @("-m", "py_compile", "updater\release_update_client.py")
        Invoke-Python -Arguments @("-m", "py_compile", "ui\main_app\window.py")
    }

    Invoke-Step -Label "Limpiando salidas anteriores del portable" -Script {
        Remove-PathIfExists -PathValue $BuildRoot
        Remove-PathIfExists -PathValue $PortableRoot
        Ensure-Directory -PathValue $DistRoot
        Ensure-Directory -PathValue $ReleasesRoot
    }

    Invoke-Step -Label "Verificando PyInstaller" -Script {
        Invoke-Python -Arguments @("-m", "PyInstaller", "--version")
    }

    Invoke-Step -Label "Verificando cache local de ms-playwright" -Script {
        Assert-PathExists -PathValue $MsPlaywrightSource -Message "No se encontro ms-playwright en $MsPlaywrightSource. BrowserManager lo requiere para el portable."
    }

    Invoke-Step -Label "Generando build portable con PyInstaller" -Script {
        Invoke-Python -Arguments @(
            "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath", $DistRoot,
            "--workpath", $BuildRoot,
            $SpecPath
        )
    }

    Invoke-Step -Label "Creando carpetas runtime vacias" -Script {
        $runtimeDirs = @(
            "logs",
            "exports",
            "updates",
            "local_data",
            "local_data\config",
            "local_data\logs",
            "local_data\debug",
            "local_data\results",
            "local_data\results\screenshots",
            "local_data\failed_uploads",
            "local_data\temp_photos"
        )
        foreach ($relativeDir in $runtimeDirs) {
            Ensure-Directory -PathValue (Join-Path $PortableRoot $relativeDir)
        }
    }

    Invoke-Step -Label "Reflejando recursos requeridos al nivel raiz del portable" -Script {
        Copy-PortableAssetFromInternal -RelativePath "browser_extension"
        Copy-PortableAssetFromInternal -RelativePath "updater"
        Copy-PortableAssetFromInternal -RelativePath "sql"

        $envExampleInternal = Join-Path $PortableRoot "_internal\.env.example"
        if (Test-Path $envExampleInternal) {
            Copy-Item -Path $envExampleInternal -Destination (Join-Path $PortableRoot ".env.example") -Force
        }
    }

    Invoke-Step -Label "Copiando ms-playwright" -Script {
        $target = Join-Path $PortableRoot "ms-playwright"
        Remove-PathIfExists -PathValue $target
        Copy-Item -Path $MsPlaywrightSource -Destination $target -Recurse -Force
    }

    Invoke-Step -Label "Preparando archivos publicos del updater" -Script {
        $updaterTargetDir = Join-Path $PortableRoot "updater"
        Ensure-Directory -PathValue $updaterTargetDir

        $exampleSource = Join-Path $ProjectRoot "updater\updater_config.example.json"
        $exampleTarget = Join-Path $updaterTargetDir "updater_config.example.json"
        Write-PortableUpdaterConfig -SourcePath $exampleSource -TargetPath $exampleTarget

        $publicConfigSource = Join-Path $ProjectRoot "updater\updater_config.json"
        if (Test-UpdaterConfigIsPublicCandidate -PathValue $publicConfigSource) {
            $publicConfigTarget = Join-Path $updaterTargetDir "updater_config.json"
            Write-PortableUpdaterConfig -SourcePath $publicConfigSource -TargetPath $publicConfigTarget
        }
    }

    Invoke-Step -Label "Validando contenido del portable" -Script {
        Assert-PathExists -PathValue (Join-Path $PortableRoot "AutoHeLlegado.exe") -Message "Falta dist\AutoHeLlegado\AutoHeLlegado.exe"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "AutoHeLlegadoUploader.exe") -Message "Falta dist\AutoHeLlegado\AutoHeLlegadoUploader.exe"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "AutoHeLlegadoDebugInspector.exe") -Message "Falta dist\AutoHeLlegado\AutoHeLlegadoDebugInspector.exe"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "AutoHeLlegadoUpdateHelper.exe") -Message "Falta dist\AutoHeLlegado\AutoHeLlegadoUpdateHelper.exe"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "updater\github_sync_updater.py") -Message "Falta dist\AutoHeLlegado\updater\github_sync_updater.py"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "updater\apply_update_helper.py") -Message "Falta dist\AutoHeLlegado\updater\apply_update_helper.py"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "updater\launchers\ActualizarApp.bat") -Message "Falta dist\AutoHeLlegado\updater\launchers\ActualizarApp.bat"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "browser_extension") -Message "Falta dist\AutoHeLlegado\browser_extension\"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "logs") -Message "Falta dist\AutoHeLlegado\logs\"
        Assert-PathExists -PathValue (Join-Path $PortableRoot "updates") -Message "Falta dist\AutoHeLlegado\updates\"
    }

    Invoke-Step -Label "Generando zip portable" -Script {
        if (Test-Path $ZipPath) {
            Remove-Item -LiteralPath $ZipPath -Force
        }
        Compress-Archive -Path $PortableRoot -DestinationPath $ZipPath -CompressionLevel Optimal
        Assert-PathExists -PathValue $ZipPath -Message "No se genero el zip final en releases\."
    }

    Write-Host ""
    Write-Host "Portable generado:" -ForegroundColor Green
    Write-Host "  $PortableRoot"
    Write-Host "Zip final:" -ForegroundColor Green
    Write-Host "  $ZipPath"
}
finally {
    Pop-Location
}

param([switch]$CompileOnly)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$compiler = Get-Command iscc.exe -ErrorAction SilentlyContinue
$iscc = if ($compiler) { $compiler.Source } else {
    @(
        "$env:USERPROFILE\scoop\shims\iscc.exe"
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $iscc) { throw 'ISCC.exe is required for installer tests.' }

$testId = [guid]::NewGuid().ToString()
$tempRoot = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path
$fixture = Join-Path $tempRoot "enikk-installer-test-$testId"
$testRegistrySubkey = "Software\EnikkInstallerTest-$testId"
$testRegistryRoot = "HKCU:\$testRegistrySubkey"
New-Item -ItemType Directory -Path $fixture | Out-Null

function Build-Installer($variant) {
    $output = Join-Path $fixture $variant
    & $iscc /Qp /DMyAppVersion=0.0.0 "/O$output" (Join-Path $fixture 'installer\enikk_installer.iss')
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed for $variant with exit code $LASTEXITCODE." }
}

function Test-Installation($variant, $scenario, $driverSelected, $driverExitCode, [switch]$DriverAlreadyInstalled) {
    $setup = Join-Path $fixture "$variant\Enikk-0.0.0-Setup.exe"
    $destination = Join-Path $fixture "installed-$scenario"
    $uninstaller = Join-Path $destination 'unins000.exe'
    $log = Join-Path $fixture "$scenario.log"
    $args = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
              '/LANG=english', "/DIR=`"$destination`"", "/LOG=`"$log`"")
    if ($driverSelected) { $args += '/TASKS=interception' }
    $env:ENIKK_TEST_DRIVER_EXIT_CODE = $driverExitCode
    try {
        $process = Start-Process -FilePath $setup -ArgumentList $args -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Setup returned $($process.ExitCode), expected 0."
        }
        if (-not (Test-Path -LiteralPath (Join-Path $destination 'enikk.exe'))) {
            throw 'Enikk application was not installed.'
        }
        if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
            throw 'Enikk uninstaller was not installed.'
        }
        $driverFiles = Join-Path $destination 'tools\Interception\Interception'
        if ($driverSelected) {
            $marker = Join-Path $driverFiles 'command line installer\driver-arguments.txt'
            if (-not (Test-Path -LiteralPath (Join-Path $driverFiles 'library\x64\interception.dll'))) {
                throw 'The selected driver DLL was not installed.'
            }
            if ($DriverAlreadyInstalled) {
                if (Test-Path -LiteralPath $marker) {
                    throw 'Setup ran the driver installer even though the driver was already installed.'
                }
            } elseif ((Get-Content -LiteralPath $marker -Raw) -cne '/install') {
                throw 'The driver test program did not receive /install.'
            }
            $expectedLog = if ($DriverAlreadyInstalled) {
                'Interception drivers are already installed. Skipping driver installation.'
            } elseif ($driverExitCode -eq 0) {
                'Interception setup succeeded. Restart Windows before using the driver.'
            } else {
                "Interception setup failed (code $driverExitCode)."
            }
            if (-not (Select-String -LiteralPath $log -SimpleMatch $expectedLog -Quiet)) {
                throw "Expected setup log entry: $expectedLog"
            }
            if (-not $DriverAlreadyInstalled -and $driverExitCode -ne 0 -and
                -not (Select-String -LiteralPath $log -SimpleMatch 'Interception test failure details' -Quiet)) {
                throw 'Setup did not log the driver installer diagnostics.'
            }
        } elseif (Test-Path -LiteralPath $driverFiles) {
            throw 'Driver files were installed without selecting the task.'
        }
    } catch {
        if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log }
        throw
    } finally {
        if (Test-Path -LiteralPath $uninstaller) {
            $process = Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -WindowStyle Hidden -Wait -PassThru
            if ($process.ExitCode -ne 0 -or (Test-Path -LiteralPath (Join-Path $destination 'enikk.exe'))) {
                throw "Uninstall failed for $scenario."
            }
        }
        Remove-Item Env:ENIKK_TEST_DRIVER_EXIT_CODE -ErrorAction SilentlyContinue
    }
    Write-Host "Passed installer scenario: $scenario"
}

try {
    foreach ($relative in @('installer', 'enikk\static', 'dist\enikk\_internal')) {
        New-Item -ItemType Directory -Path (Join-Path $fixture $relative) | Out-Null
    }
    Copy-Item -LiteralPath "$repo\LICENSE" -Destination $fixture
    Copy-Item -LiteralPath "$repo\installer\ChineseSimplified.isl" -Destination "$fixture\installer"
    Copy-Item -LiteralPath "$repo\enikk\static\enikk-logo.ico" -Destination "$fixture\enikk\static"
    # Isolate the fixture from any Enikk installation and its uninstall registry entry.
    $source = Get-Content -LiteralPath "$repo\installer\enikk_installer.iss" -Raw
    $source.Replace('C5C5100B-32E9-4826-B744-A0B60A4A60F4', $testId).
        Replace('#define MyAppName "Enikk"', '#define MyAppName "Enikk Installer Test"').
        Replace('RegQueryMultiStringValue(HKLM, ClassKey', 'RegQueryMultiStringValue(HKCU, ClassKey').
        Replace("RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\", "RegKeyExists(HKCU, '$testRegistrySubkey\Services\").
        Replace("'SYSTEM\CurrentControlSet\Control\Class\'", "'$testRegistrySubkey\Class\'").
        Replace('{sys}\drivers\', '{src}\existing-drivers\') |
        Set-Content -LiteralPath "$fixture\installer\enikk_installer.iss" -Encoding utf8BOM
    Set-Content -LiteralPath "$fixture\dist\enikk\enikk.exe" -Value 'App fixture'
    Set-Content -LiteralPath "$fixture\dist\enikk\_internal\fixture.txt" -Value 'App payload fixture'
    Build-Installer 'base'

    $driver = Join-Path $fixture 'tools\Interception\Interception'
    foreach ($relative in @('command line installer', 'library\x64', 'licenses\non-commercial-usage')) {
        New-Item -ItemType Directory -Path (Join-Path $driver $relative) | Out-Null
    }
    Set-Content -LiteralPath "$driver\library\x64\interception.dll" -Value 'DLL fixture'
    Set-Content -LiteralPath "$driver\licenses\non-commercial-usage\LGPL 3.0.txt" -Value 'License fixture'
    @'
using System;
using System.IO;

static class DriverInstaller {
    static int Main(string[] args) {
        File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "driver-arguments.txt"),
                          String.Join(" ", args));
        int code = Int32.Parse(Environment.GetEnvironmentVariable("ENIKK_TEST_DRIVER_EXIT_CODE"));
        if (code != 0)
            Console.Error.WriteLine("Interception test failure details");
        return code;
    }
}
'@ | Set-Content -LiteralPath "$fixture\driver-installer.cs"
    $csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    & $csc /nologo "/out:$driver\command line installer\install-interception.exe" "$fixture\driver-installer.cs"
    if ($LASTEXITCODE -ne 0) { throw "Building the driver test program failed with exit code $LASTEXITCODE." }
    Build-Installer 'with-driver'

    if (-not $CompileOnly) {
        Test-Installation 'base' 'without-driver-assets' $false 0
        Test-Installation 'with-driver' 'default-selection' $false 0
        Test-Installation 'with-driver' 'driver-success' $true 0
        Test-Installation 'with-driver' 'driver-failure' $true 1

        $driverState = Join-Path $fixture 'with-driver\existing-drivers'
        New-Item -ItemType Directory -Path $driverState | Out-Null
        foreach ($driverName in @('mouse', 'keyboard')) {
            New-Item -ItemType File -Path (Join-Path $driverState "$driverName.sys") | Out-Null
            New-Item -Path "$testRegistryRoot\Services\$driverName" -Force | Out-Null
        }
        $mouseClass = "$testRegistryRoot\Class\{4d36e96f-e325-11ce-bfc1-08002be10318}"
        $keyboardClass = "$testRegistryRoot\Class\{4d36e96b-e325-11ce-bfc1-08002be10318}"
        New-Item -Path $mouseClass, $keyboardClass -Force | Out-Null
        New-ItemProperty -LiteralPath $mouseClass -Name UpperFilters -PropertyType MultiString -Value @('mouse', 'mouclass') | Out-Null
        New-ItemProperty -LiteralPath $keyboardClass -Name UpperFilters -PropertyType MultiString -Value @('kbdclass') | Out-Null
        Test-Installation 'with-driver' 'driver-partially-installed' $true 0
        Set-ItemProperty -LiteralPath $keyboardClass -Name UpperFilters -Value @('keyboard', 'kbdclass')
        Test-Installation 'with-driver' 'driver-already-installed' $true 1 -DriverAlreadyInstalled
    }
} finally {
    if (Test-Path -LiteralPath $testRegistryRoot) {
        Remove-Item -LiteralPath $testRegistryRoot -Recurse -Force
    }
    $resolvedFixture = (Resolve-Path -LiteralPath $fixture).Path
    if ($resolvedFixture -ne (Join-Path $tempRoot "enikk-installer-test-$testId")) {
        throw "Unexpected installer fixture path: $resolvedFixture"
    }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}

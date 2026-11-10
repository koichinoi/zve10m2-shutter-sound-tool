param(
    [Parameter(Mandatory)] [string] $JavaHome,
    [Parameter(Mandatory)] [string] $AndroidJar,
    [Parameter(Mandatory)] [string] $BuildTools,
    [string] $ServiceAuth,
    [string] $PreparedSound,
    [string] $CustomSound,
    [string] $CameraLooks,
    [string] $CameraLut,
    [string] $AlternateCameraLut,
    [string] $LutTemplates,
    [string] $BuiltInLuts,
    [string] $CameraIcons,
    [string] $ExtraCameraIcons,
    [string] $Display32CameraIcons,
    [string] $Output = (Join-Path $PSScriptRoot 'build/ZVE10-II-Android-0.2.9.apk')
)

$ErrorActionPreference = 'Stop'
$env:JAVA_HOME = (Resolve-Path -LiteralPath $JavaHome).Path
$AndroidJar = (Resolve-Path -LiteralPath $AndroidJar).Path
$BuildTools = (Resolve-Path -LiteralPath $BuildTools).Path
$javaBin = Join-Path $env:JAVA_HOME 'bin'
$outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
$build = Join-Path ([IO.Path]::GetTempPath()) ('zve-android-' + [Guid]::NewGuid().ToString('N'))

function Invoke-Checked([string] $Program, [string[]] $Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program returned $LASTEXITCODE" }
}

$classes = Join-Path $build 'classes'
$assets = Join-Path $build 'assets'
$unsigned = Join-Path $build 'unsigned.apk'
$aligned = Join-Path $build 'aligned.apk'
$dex = Join-Path $build 'classes.dex'
$manifest = Join-Path $build 'AndroidManifest.xml'
$signed = Join-Path $build 'signed.apk'
try {
New-Item -ItemType Directory -Force $classes, $assets, ([IO.Path]::GetDirectoryName($outputPath)) | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../filters/FL2-FL3.json') -Destination $assets -Force
if ($ServiceAuth) {
    $authFile = Get-Item -LiteralPath $ServiceAuth
    if ($authFile.Length -ne 3072) { throw 'Invalid service authentication asset' }
    Copy-Item -LiteralPath $authFile.FullName -Destination (Join-Path $assets 'sony-service-auth.bin')
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'AndroidManifest.xml') -Destination $manifest
$sources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src') -Recurse -Filter '*.java' | ForEach-Object FullName)
Invoke-Checked (Join-Path $javaBin 'javac.exe') (@('--release', '8', '-encoding', 'UTF-8', '-classpath', $AndroidJar, '-d', $classes) + $sources)
$classFiles = @($sources | ForEach-Object {
    $class = [IO.Path]::GetFileNameWithoutExtension($_)
    Get-ChildItem -LiteralPath (Join-Path $classes 'io/github/koichinoi/zve10tool') -Filter "$class*.class" | ForEach-Object FullName
})
Invoke-Checked (Join-Path $BuildTools 'd8.bat') (@('--lib', $AndroidJar, '--min-api', '26', '--output', $build) + $classFiles)
$res = Join-Path $build 'res'
$compiledRes = Join-Path $build 'res.zip'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'res') -Destination $res -Recurse
$aapt = Join-Path $BuildTools 'aapt2.exe'
Invoke-Checked $aapt @('compile', '--dir', $res, '-o', $compiledRes)
Invoke-Checked $aapt @('link', '-I', $AndroidJar, '--manifest', $manifest, '-A', $assets, '-o', $unsigned, $compiledRes)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$apk = [IO.Compression.ZipFile]::Open($unsigned, [IO.Compression.ZipArchiveMode]::Update)
try {
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $dex, 'classes.dex') | Out-Null
    if ($PreparedSound) {
        foreach ($name in 'manifest.json', 'worker.so', 'audio.bin') {
            # Android AssetManager requires forward slashes inside the APK.
            $file = (Resolve-Path -LiteralPath (Join-Path $PreparedSound $name)).Path
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/prepared-sound/$name") | Out-Null
        }
    }
    if ($CustomSound) {
        foreach ($name in 'manifest.json', 'worker.so', 'guard.bin') {
            $file = (Resolve-Path -LiteralPath (Join-Path $CustomSound $name)).Path
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/custom-sound/$name") | Out-Null
        }
    }
    if ($CameraLooks) {
        foreach ($name in 'manifest.json', 'cp.so', 'wbi.so', 'restore.so') {
            $file = (Resolve-Path -LiteralPath (Join-Path $CameraLooks $name)).Path
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/camera-looks/$name") | Out-Null
        }
    }
    if ($CameraLut) {
        if (!$ServiceAuth) { throw 'Camera LUT import requires local service authentication' }
        foreach ($name in 'manifest.json', 'cp.so', 'wbi.so', 'restore.so') {
            $file = (Resolve-Path -LiteralPath (Join-Path $CameraLut $name)).Path
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/camera-lut/$name") | Out-Null
        }
    }
    if ($AlternateCameraLut) {
        if (!$CameraLut) { throw 'Alternate LUT requires the primary LUT package' }
        foreach ($name in 'manifest.json', 'cp.so', 'wbi.so', 'restore.so') {
            $file = (Resolve-Path -LiteralPath (Join-Path $AlternateCameraLut $name)).Path
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/camera-lut-alt/$name") | Out-Null
        }
    }
    if ($LutTemplates) {
        if (!$CameraLut) { throw 'Custom LUT templates require a prepared camera LUT baseline' }
        foreach ($name in 'manifest.json', 'cp.so', 'restore.so', 'baseline.bin') {
            $file = (Resolve-Path -LiteralPath (Join-Path $LutTemplates $name)).Path
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/lut-templates/$name") | Out-Null
        }
    }
    if ($BuiltInLuts) {
        if (!$LutTemplates) { throw 'Built-in LUT selection requires the custom LUT templates' }
        $lutFiles = @(Get-ChildItem -LiteralPath $BuiltInLuts -Filter '*.cube' -File -Recurse | Sort-Object Name, FullName)
        if (!$lutFiles.Count) { throw 'No .cube files found in the LUT library' }
        $catalog = for ($i = 0; $i -lt $lutFiles.Count; $i++) {
            $lut = $lutFiles[$i]
            if ($lut.Length -gt 24MB) { throw "LUT exceeds 24 MB: $($lut.Name)" }
            $filename = ('{0:D3}.cube' -f ($i + 1))
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $lut.FullName, "assets/builtin-luts/$filename") | Out-Null
            @{ name = $lut.BaseName; file = $filename }
        }
        $catalogEntry = $apk.CreateEntry('assets/builtin-luts/catalog.json')
        $writer = [IO.StreamWriter]::new($catalogEntry.Open(), [Text.UTF8Encoding]::new($false))
        try { $writer.Write((ConvertTo-Json -InputObject @($catalog) -Compress)) } finally { $writer.Dispose() }
    }
    if ($CameraIcons) {
        $names = @('manifest.json') + @(1..4 | ForEach-Object { "install$_.so"; "restore$_.so" })
        foreach ($name in $names) {
            $file = (Resolve-Path -LiteralPath (Join-Path $CameraIcons $name)).Path
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/camera-icons/$name") | Out-Null
        }
    }
    if ($ExtraCameraIcons) {
        if (!$CameraIcons) { throw 'Extra camera icons require the base icon resources' }
        foreach ($bank in 1, 2) {
            foreach ($name in 'manifest.json', 'install1.so', 'restore1.so') {
                $file = (Resolve-Path -LiteralPath (Join-Path $ExtraCameraIcons "bank$bank/workers/$name")).Path
                [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/camera-icons/extra$bank/$name") | Out-Null
            }
        }
    }
    if ($Display32CameraIcons) {
        if (!$CameraIcons -or !$ExtraCameraIcons) { throw '32_IPSX requires the 23_IPSX icon resources' }
        foreach ($bank in 1, 2) {
            $count = if ($bank -eq 1) { 4 } else { 1 }
            $names = @('manifest.json') + @(1..$count | ForEach-Object { "install$_.so"; "restore$_.so" })
            foreach ($name in $names) {
                $file = (Resolve-Path -LiteralPath (Join-Path $Display32CameraIcons "bank$bank/workers/$name")).Path
                [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($apk, $file, "assets/camera-icons/display32b$bank/$name") | Out-Null
            }
        }
    }
} finally { $apk.Dispose() }
Invoke-Checked (Join-Path $BuildTools 'zipalign.exe') @('-f', '4', $unsigned, $aligned)

$keyDir = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force $keyDir | Out-Null
$key = Join-Path $keyDir 'debug.keystore'
if (-not (Test-Path -LiteralPath $key)) {
    Invoke-Checked (Join-Path $javaBin 'keytool.exe') @('-genkeypair', '-keystore', $key, '-storepass', 'android', '-keypass', 'android',
        '-alias', 'androiddebugkey', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000', '-dname', 'CN=Android Debug')
}
Invoke-Checked (Join-Path $BuildTools 'apksigner.bat') @('sign', '--ks', $key, '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--out', $signed, $aligned)
Invoke-Checked (Join-Path $BuildTools 'apksigner.bat') @('verify', '--verbose', $signed)
Copy-Item -LiteralPath $signed -Destination $outputPath -Force
Get-Item -LiteralPath $outputPath
} finally {
    $resolvedBuild = Resolve-Path -LiteralPath $build -ErrorAction SilentlyContinue
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedBuild -and $resolvedBuild.Path.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedBuild.Path -Recurse -Force
    }
}

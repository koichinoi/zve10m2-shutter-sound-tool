param(
    [Parameter(Mandatory)] [string] $JavaHome,
    [Parameter(Mandatory)] [string] $AndroidJar,
    [Parameter(Mandatory)] [string] $BuildTools,
    [string] $ServiceAuth,
    [string] $PreparedSound,
    [string] $Output = (Join-Path $PSScriptRoot 'build/ZVE10-II-Android-0.1.6.apk')
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
Invoke-Checked (Join-Path $BuildTools 'aapt2.exe') @('link', '-I', $AndroidJar, '--manifest', $manifest, '-A', $assets, '-o', $unsigned)
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

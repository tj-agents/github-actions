param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$')]
    [string]$Owner,
    [Parameter(Mandatory = $true)]
    [string]$ResultFile,
    [switch]$Interactive
)

$ErrorActionPreference = 'Stop'

if ($env:TJ_AGENT -eq '1' -or $env:GH_TOKEN -or $env:GITHUB_TOKEN -or $env:GH_CONFIG_DIR) {
    throw "Owner setup requires your own GitHub sign-in. Invoke this launcher through the prepared native ! command."
}
if ($env:OS -ne 'Windows_NT') {
    throw 'Use the locked owner_setup.py command in your own terminal on this platform.'
}

$ownerResultPath = [IO.Path]::GetFullPath($ResultFile)
$ownerSetupPath = Join-Path $PSScriptRoot 'owner_setup.py'
$ownerUv = (Get-Command uv.exe -CommandType Application -ErrorAction Stop).Source
$ownerGh = (Get-Command gh.exe -CommandType Application -ErrorAction Stop).Source
$env:PATH = "$(Split-Path -Parent $ownerGh);$env:PATH"

if (-not $Interactive) {
    if (Test-Path -LiteralPath $ownerResultPath) {
        $ownerPrevious = Get-Content -LiteralPath $ownerResultPath -Raw | ConvertFrom-Json
        if ($ownerPrevious.owner -ne $Owner) {
            throw 'The result file belongs to another organization. Use its owning result file.'
        }
        if ($ownerPrevious.state -eq 'running' -and $ownerPrevious.pid) {
            $ownerRunning = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$ownerPrevious.pid)"
            if ($ownerRunning) {
                if (-not $ownerRunning.CommandLine -or -not $ownerRunning.CommandLine.Contains($ownerSetupPath)) {
                    throw 'The recorded process identity changed. Inspect the result before retrying.'
                }
                Write-Host "Owner setup is already running. Its result is $ownerResultPath"
                return
            }
        }
    }
    $ownerChild = Start-Process powershell.exe -WindowStyle Normal -PassThru -ArgumentList @(
        '-NoExit', '-NoProfile', '-File', "`"$PSCommandPath`"",
        '-Owner', $Owner, '-ResultFile', "`"$ownerResultPath`"", '-Interactive'
    )
    Write-Host "Owner setup window started (process $($ownerChild.Id))."
    Write-Host "Follow its browser and local key prompts. Progress and the result are saved to $ownerResultPath"
    return
}

Write-Host "Owner setup will show its current step below. Result: $ownerResultPath"
$ownerStartedAt = [DateTime]::UtcNow
& $ownerUv run --locked --script $ownerSetupPath --owner $Owner --apply --result-file $ownerResultPath
$ownerExitCode = $LASTEXITCODE
$ownerFinal = if (Test-Path -LiteralPath $ownerResultPath) {
    Get-Content -LiteralPath $ownerResultPath -Raw | ConvertFrom-Json
} else {
    $null
}
$ownerResultIsCurrent = $null -ne $ownerFinal -and $ownerFinal.owner -eq $Owner -and
    [DateTime]::Parse($ownerFinal.observed_at).ToUniversalTime() -ge $ownerStartedAt
if ($ownerExitCode -ne 0 -and (-not $ownerResultIsCurrent -or $ownerFinal.state -ne 'failed')) {
    $ownerFailure = @{
        schema_version = 1
        owner = $Owner
        pid = $PID
        state = 'failed'
        phase = 'Starting locked owner setup'
        exit_code = $ownerExitCode
        error = "Locked owner setup exited with code $ownerExitCode before saving its failure result."
        observed_at = [DateTime]::UtcNow.ToString('o')
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($ownerResultPath)) > $null
    $ownerTemporary = "$ownerResultPath.$PID.tmp"
    [IO.File]::WriteAllText($ownerTemporary, ($ownerFailure | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $ownerTemporary -Destination $ownerResultPath -Force
}
if ($ownerExitCode -eq 0) {
    Write-Host 'Owner setup finished. Its result is ready for agent verification.'
} else {
    Write-Host 'Owner setup stopped. The agent can read its failure result; no console output needs copying.'
}
exit $ownerExitCode

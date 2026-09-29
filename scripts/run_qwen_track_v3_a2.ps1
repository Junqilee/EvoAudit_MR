param(
    [string]$CsvPath = "..\aliyun-apiKey-6654193.csv",
    [string]$Output = "artifacts_llm\qwen_track_v3"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

try {
    $keyLine = Get-Content -LiteralPath $CsvPath |
        Where-Object { $_ -match '^apiKey,' } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($keyLine)) {
        throw "Workspace API key was not found in the configured CSV."
    }
    $key = ($keyLine -split ',', 2)[1].Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($key)) {
        throw "Workspace API key is blank."
    }
    $env:EVOAUDIT_QWEN_API_KEY = $key
    & .\.venv\Scripts\python.exe -m evoaudit_mr.runners.qwen_track_v1 `
        --mode a2 `
        --manifest configs\qwen_track_v1_manifest.json `
        --model-config configs\qwen_track_v3_model.json `
        --offline configs\qwen_track_v1_offline.json `
        --output $Output
    if ($LASTEXITCODE -ne 0) {
        throw "Qwen A2 runner exited with code $LASTEXITCODE."
    }
    "completed" | Set-Content -NoNewline -Encoding utf8 (Join-Path $Output "A2_RUN_STATUS.txt")
}
catch {
    $_ | Out-File -Encoding utf8 (Join-Path $Output "A2_RUN_ERROR.txt")
    exit 1
}

<# Reports only whether expected secrets are present; it never prints values. #>
[CmdletBinding()]
param()

foreach ($name in "EVOAUDIT_QWEN_API_KEY", "EVOAUDIT_DEEPSEEK_API_KEY") {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    $status = if ([string]::IsNullOrWhiteSpace($value)) { "missing" } else { "configured" }
    Write-Host "$name : $status"
}

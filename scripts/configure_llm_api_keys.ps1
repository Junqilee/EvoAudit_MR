<#
Sets EvoAudit-MR API keys in the current process and the current Windows user
profile without creating a plaintext file. Run this yourself in PowerShell;
do not paste keys into chat, source control, or experiment configs.
#>
[CmdletBinding()]
param(
    [ValidateSet("qwen", "deepseek", "both")]
    [string]$Provider = "both"
)

$ErrorActionPreference = "Stop"

function Set-EvoAuditSecret {
    param([Parameter(Mandatory = $true)][string]$Name)
    $secure = Read-Host -Prompt "Paste $Name (input is hidden)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "$Name cannot be empty."
        }
        [Environment]::SetEnvironmentVariable($Name, $value, "User")
        Set-Item -Path "Env:$Name" -Value $value
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    Write-Host "$Name is configured for this PowerShell process and future user sessions."
}

if ($Provider -in @("qwen", "both")) { Set-EvoAuditSecret -Name "EVOAUDIT_QWEN_API_KEY" }
if ($Provider -in @("deepseek", "both")) { Set-EvoAuditSecret -Name "EVOAUDIT_DEEPSEEK_API_KEY" }

Write-Host "Open a new PowerShell window before running experiment commands outside this session."

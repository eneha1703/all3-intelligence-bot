param(
    [string]$GithubToken = "",
    [string]$Owner = "eneha1703",
    [string]$Repository = "all3-intelligence-bot",
    [Parameter(Mandatory = $true)]
    [string]$TelegramAlertChatIds,
    [string]$TelegramDigestChatIds = "",
    [string]$ShortlistReactionAllowlist = "emoji:star"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($GithubToken)) {
    $GithubToken = $env:GITHUB_RADAR_TRIGGER_TOKEN
}
if ([string]::IsNullOrWhiteSpace($GithubToken)) {
    $GithubToken = [System.Environment]::GetEnvironmentVariable("GITHUB_RADAR_TRIGGER_TOKEN", "User")
}
if ([string]::IsNullOrWhiteSpace($GithubToken)) {
    throw "GitHub token is not configured. Pass -GithubToken or set GITHUB_RADAR_TRIGGER_TOKEN."
}

$GithubToken = $GithubToken.Trim()
$TelegramAlertChatIds = $TelegramAlertChatIds.Trim()
if ([string]::IsNullOrWhiteSpace($TelegramAlertChatIds)) {
    throw "Telegram alert chat IDs are required."
}

if ([string]::IsNullOrWhiteSpace($TelegramDigestChatIds)) {
    $TelegramDigestChatIds = $TelegramAlertChatIds
}

$variables = [ordered]@{
    "TELEGRAM_ALERT_CHAT_IDS"                 = $TelegramAlertChatIds
    "TELEGRAM_DIGEST_CHAT_IDS"                = $TelegramDigestChatIds.Trim()
    "CLAUDE_EDITORIAL_ENABLED"                = "true"
    "CLAUDE_EDITORIAL_MAX_CANDIDATES"         = "12"
    "CLAUDE_EDITORIAL_MODEL"                  = "claude-sonnet-4-6"
    "CLAUDE_EDITORIAL_TIMEOUT_SECONDS"        = "30"
    "CLAUDE_EDITORIAL_MAX_TOKENS"             = "900"
    "CLAUDE_FINAL_CARD_ENABLED"               = "true"
    "CLAUDE_FINAL_CARD_MAX_CANDIDATES"        = "15"
    "CLAUDE_FINAL_CARD_MODEL"                 = "claude-sonnet-4-6"
    "CLAUDE_FINAL_CARD_TIMEOUT_SECONDS"       = "30"
    "CLAUDE_FINAL_CARD_MAX_TOKENS"            = "900"
    "TELEGRAM_GROUP_CURATION_ENABLED"         = "true"
    "TELEGRAM_GROUP_MESSAGE_INGEST_ENABLED"   = "true"
    "TELEGRAM_REACTION_SHORTLIST_ENABLED"     = "true"
    "TELEGRAM_SHORTLIST_REACTION_ALLOWLIST"   = $ShortlistReactionAllowlist.Trim()
    "TELEGRAM_SHORTLIST_WINDOW_DAYS"          = "7"
    "TELEGRAM_SHORTLIST_MIN_UNIQUE_REACTORS"  = "1"
}

$baseUri = "https://api.github.com/repos/$Owner/$Repository/actions/variables"
$headers = @{
    "Authorization" = "Bearer $GithubToken"
    "Accept"        = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"    = "all3-radar-variable-bootstrap"
}

$existingResponse = Invoke-RestMethod -Method Get -Uri $baseUri -Headers $headers
$existingNames = @{}
foreach ($item in ($existingResponse.variables | Where-Object { $_ -and $_.name })) {
    $existingNames[$item.name] = $true
}

foreach ($entry in $variables.GetEnumerator()) {
    $body = @{
        value = $entry.Value
    } | ConvertTo-Json -Compress

    if ($existingNames.ContainsKey($entry.Key)) {
        $updateUri = "$baseUri/$($entry.Key)"
        Invoke-RestMethod -Method Patch -Uri $updateUri -Headers $headers -ContentType "application/json" -Body $body | Out-Null
        Write-Host "Updated $($entry.Key)"
    } else {
        $createBody = @{
            name  = $entry.Key
            value = $entry.Value
        } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method Post -Uri $baseUri -Headers $headers -ContentType "application/json" -Body $createBody | Out-Null
        Write-Host "Created $($entry.Key)"
    }
}

Write-Host "Repository variables synchronized for $Owner/$Repository"

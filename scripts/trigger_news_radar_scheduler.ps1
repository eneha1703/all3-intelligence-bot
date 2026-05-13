param(
  [string]$GithubToken = "",

  [string]$Owner = "egalimova-eng",

  [string]$Repository = "all3_intelligence_radar",

  [string]$WorkflowId = "radar-scheduler.yml",

  [string]$Ref = "main",

  [bool]$DryRun = $false
)

if ([string]::IsNullOrWhiteSpace($GithubToken)) {
  $GithubToken = [System.Environment]::GetEnvironmentVariable("GITHUB_RADAR_TRIGGER_TOKEN", "User")
}

if ([string]::IsNullOrWhiteSpace($GithubToken)) {
  throw "GITHUB_RADAR_TRIGGER_TOKEN is not set and -GithubToken was not provided."
}

$headers = @{
  Accept                 = "application/vnd.github+json"
  Authorization          = "Bearer $GithubToken"
  "X-GitHub-Api-Version" = "2022-11-28"
  "User-Agent"           = "all3-news-radar-trigger"
}

$body = @{
  ref    = $Ref
  inputs = @{
    dry_run = if ($DryRun) { "true" } else { "false" }
  }
} | ConvertTo-Json -Depth 4 -Compress

$uri = "https://api.github.com/repos/$Owner/$Repository/actions/workflows/$WorkflowId/dispatches"

Invoke-RestMethod `
  -Method Post `
  -Headers $headers `
  -Uri $uri `
  -ContentType "application/json; charset=utf-8" `
  -Body $body

param(
  [Parameter(Mandatory = $true)]
  [string]$GithubToken,

  [string]$Repository = "egalimova-eng/all3_intelligence_radar",

  [string]$EventType = "news-radar"
)

$headers = @{
  Accept        = "application/vnd.github+json"
  Authorization = "Bearer $GithubToken"
  "User-Agent"  = "all3-intelligence-radar-dispatch"
}

$body = @{
  event_type = $EventType
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Method Post `
  -Headers $headers `
  -Uri "https://api.github.com/repos/$Repository/dispatches" `
  -ContentType "application/json; charset=utf-8" `
  -Body $body

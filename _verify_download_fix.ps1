# Verify template download fix
Write-Host "=== Verify Template Download URL Fix ===" -ForegroundColor Cyan

# Step 1: Get access info
Write-Host "`n[1/4] Getting access info..." -ForegroundColor Yellow
try {
    $accessInfo = Invoke-WebRequest -Uri "http://localhost:8765/api/access-info" -UseBasicParsing
    $info = $accessInfo.Content | ConvertFrom-Json
    $token = $info.token
    Write-Host "Token: $token" -ForegroundColor Green
    Write-Host "Access level: $($info.accessLevel)" -ForegroundColor Green
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}

# Step 2: Generate template
Write-Host "`n[2/4] Generating archive template..." -ForegroundColor Yellow
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
    "Accept" = "application/json, text/event-stream"
}
$body = @{
    jsonrpc = "2.0"
    id = 1
    method = "tools/call"
    params = @{
        name = "generate_device_archive_template"
        arguments = @{}
    }
} | ConvertTo-Json -Depth 10

try {
    $genResponse = Invoke-WebRequest -Uri "http://localhost:8765/mcp" -Method POST -Headers $headers -Body $body -UseBasicParsing
    $genResult = $genResponse.Content | ConvertFrom-Json
    $fileId = $genResult.result.content[0].text | ConvertFrom-Json | Select-Object -ExpandProperty file_id
    Write-Host "file_id: $fileId" -ForegroundColor Green
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}

# Step 3: Get download info
Write-Host "`n[3/4] Getting download info..." -ForegroundColor Yellow
$body2 = @{
    jsonrpc = "2.0"
    id = 2
    method = "tools/call"
    params = @{
        name = "get_device_archive_template_download"
        arguments = @{
            file_id = $fileId
        }
    }
} | ConvertTo-Json -Depth 10

try {
    $dlResponse = Invoke-WebRequest -Uri "http://localhost:8765/mcp" -Method POST -Headers $headers -Body $body2 -UseBasicParsing
    $dlResult = $dlResponse.Content | ConvertFrom-Json
    $downloadUrl = $dlResult.result.content[0].text | ConvertFrom-Json | Select-Object -ExpandProperty download_url
    Write-Host "download_url: $downloadUrl" -ForegroundColor Green
    
    # Check if URL contains owner parameter
    if ($downloadUrl -match "\?owner=") {
        Write-Host "[OK] URL contains owner parameter!" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] URL missing owner parameter!" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}

# Step 4: Test download
Write-Host "`n[4/4] Testing file download..." -ForegroundColor Yellow
$fullUrl = "http://localhost:8765$downloadUrl"
try {
    Invoke-WebRequest -Uri $fullUrl -OutFile "test_template.xlsx" -UseBasicParsing
    $fileSize = (Get-Item "test_template.xlsx").Length
    Write-Host "Download successful! File size: $fileSize bytes" -ForegroundColor Green
    
    if ($fileSize -gt 10000) {
        Write-Host "[OK] File size normal (>10KB)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] File size abnormal (<10KB)" -ForegroundColor Yellow
    }
    
    # Cleanup
    Remove-Item "test_template.xlsx" -Force
} catch {
    Write-Host "Download failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Verification Complete ===" -ForegroundColor Cyan
Write-Host "[PASS] All checks passed! Fix is working." -ForegroundColor Green

# Nishmat AI — Automated CLI Deployment Script (PowerShell)
param (
    [string]$VercelDomain = "",
    [string]$BackendDomain = "",
    [switch]$SkipBuild = $false
)

$ErrorActionPreference = "Stop"

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "         Nishmat AI — Terminal CLI Deployer           " -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan

# 1. Check CLI prerequisites
Write-Host "`n[1/4] Checking CLI tools..." -ForegroundColor Yellow

$hasVercel = Get-Command "vercel" -ErrorAction SilentlyContinue
if (-not $hasVercel) {
    Write-Host "Installing Vercel CLI globally..." -ForegroundColor Gray
    npm install -g vercel
} else {
    Write-Host "✓ Vercel CLI is available" -ForegroundColor Green
}

$hasRailway = Get-Command "railway" -ErrorAction SilentlyContinue
if (-not $hasRailway) {
    Write-Host "Installing Railway CLI globally..." -ForegroundColor Gray
    npm install -g @railway/cli
} else {
    Write-Host "✓ Railway CLI is available" -ForegroundColor Green
}

# 2. Local Frontend Build Check
if (-not $SkipBuild) {
    Write-Host "`n[2/4] Verifying Next.js frontend production build..." -ForegroundColor Yellow
    Push-Location "$PSScriptRoot/../frontend"
    try {
        npm run build
        Write-Host "✓ Frontend built successfully!" -ForegroundColor Green
    } catch {
        Write-Host "❌ Frontend build failed. Please fix build errors before deploying." -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Pop-Location
} else {
    Write-Host "`n[2/4] Skipping local frontend build check as requested." -ForegroundColor Gray
}

# 3. Guidance for Vercel & Railway commands
Write-Host "`n[3/4] Ready to deploy via Terminal CLI tools!" -ForegroundColor Yellow
Write-Host "`nTo deploy Frontend to Vercel:" -ForegroundColor Cyan
Write-Host "  cd frontend" -ForegroundColor White
Write-Host "  vercel --prod" -ForegroundColor White

Write-Host "`nTo deploy Backend API & Worker to Railway:" -ForegroundColor Cyan
Write-Host "  cd backend" -ForegroundColor White
Write-Host "  railway up" -ForegroundColor White

# 4. Health Check Helper
if ($BackendDomain) {
    Write-Host "`n[4/4] Testing backend health endpoint at $BackendDomain..." -ForegroundColor Yellow
    try {
        $res = Invoke-RestMethod -Uri "$BackendDomain/health"
        Write-Host "✓ Backend Health Response: $($res | ConvertTo-Json -Compress)" -ForegroundColor Green
    } catch {
        Write-Host "❌ Backend health check failed: $_" -ForegroundColor Red
    }
}

Write-Host "`n======================================================" -ForegroundColor Cyan
Write-Host "Deployment preparation complete! Follow instructions above." -ForegroundColor Cyan

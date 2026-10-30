# attack.ps1 - laptop-side attacker for the live remote-attack demo.
# Fires real TCP SYNs from THIS machine at the EC2 node's public IP over the internet.
# The node's agent (device-2) captures them on its real NIC, classifies, and firewalls you.
# Usage:   powershell -ExecutionPolicy Bypass -File .\attack.ps1
#          powershell -ExecutionPolicy Bypass -File .\attack.ps1 -Target 3.109.0.101 -Mode scan
# Modes:   scan  (port sweep, default)   |   flood  (rapid SYN burst = DoS shape)
param(
  [string]$Target = "3.109.0.101",   # device-2 public IP
  [string]$Mode   = "scan"
)

function Send-Syn($ip, $port, $timeoutMs = 500) {
  $c = New-Object System.Net.Sockets.TcpClient
  try { $iar = $c.BeginConnect($ip, $port, $null, $null); $null = $iar.AsyncWaitHandle.WaitOne($timeoutMs) } catch {}
  finally { $c.Close() }
}

Write-Host "==============================================================" -ForegroundColor Red
Write-Host "  ATTACK  ->  $env:COMPUTERNAME  hitting EC2 node $Target  (mode=$Mode)" -ForegroundColor Red
Write-Host "==============================================================" -ForegroundColor Red

if ($Mode -eq "flood") {
  Write-Host "SYN flood: 300 rapid connects to :8080 ..." -ForegroundColor Yellow
  1..300 | ForEach-Object { Send-Syn $Target 8080 120 }
  Write-Host "flood sent." -ForegroundColor Yellow
}
else {
  $ports = 21,22,23,25,53,80,110,135,139,143,443,445,1433,3306,3389,5432,8080,8443
  Write-Host ("port scan: {0} ports ..." -f $ports.Count) -ForegroundColor Yellow
  foreach ($p in $ports) { Send-Syn $Target $p 500; Write-Host ("  SYN -> {0}:{1}" -f $Target,$p) }
  Write-Host "scan sent." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Now watch the agent react on device-2:" -ForegroundColor Cyan
Write-Host "  (SSM session on device-2)  ->  fg-watch" -ForegroundColor Cyan
Write-Host "  it will BLOCK your IP within a few seconds, with confidence + attention." -ForegroundColor Cyan

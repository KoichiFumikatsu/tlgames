param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]]$BackupPaths
)

foreach ($backupPath in $BackupPaths) {
    if (-not (Test-Path -LiteralPath $backupPath)) {
        throw "No existe el backup: $backupPath"
    }

    if ($backupPath -notmatch "\.agent-bak$") {
        throw "El archivo no termina en .agent-bak: $backupPath"
    }

    $targetPath = $backupPath -replace "\.agent-bak$", ""
    Copy-Item -LiteralPath $backupPath -Destination $targetPath -Force
    Write-Output "Restaurado: $targetPath"
}

param(
    [Parameter(Mandatory=$false)]
    [string]$RepoRoot = ".",

    [Parameter(Mandatory=$false)]
    [string]$UserAgent = "Orion-PIT-research/1.0 your-email@example.com"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PitDir = Join-Path $RepoRoot "PIT input data"
$Gaps = Join-Path $PitDir "SEC_SECURITY_TYPE_BUY_COVERAGE_GAPS.csv"
$Out = Join-Path $PitDir "SEC_COVERPAGE_SECURITY_TYPE_EVIDENCE.csv"
$Unresolved = Join-Path $PitDir "SEC_COVERPAGE_SECURITY_TYPE_UNRESOLVED.csv"
$Report = Join-Path $PitDir "SEC_COVERPAGE_SECURITY_TYPE_REPORT.json"

if (-not (Test-Path $Gaps)) {
    throw "Missing input file: $Gaps"
}

$Headers = @{
    "User-Agent" = $UserAgent
    "Accept-Encoding" = "identity"
}

$Forms = @(
    "10-K","10-K/A","10-Q","10-Q/A",
    "20-F","20-F/A","40-F","40-F/A",
    "S-1","S-1/A","F-1","F-1/A"
)

function Invoke-SecGet {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$Retries = 5
    )

    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -Headers $Headers -UseBasicParsing -TimeoutSec 45
            Start-Sleep -Milliseconds 150
            return $r.Content
        }
        catch {
            $status = $null
            if ($_.Exception.Response) {
                try { $status = [int]$_.Exception.Response.StatusCode } catch {}
            }

            if ($status -eq 404) {
                throw
            }

            if ($i -eq $Retries) {
                throw
            }

            Start-Sleep -Seconds ([Math]::Min(12, 2 * $i))
        }
    }
}

function Normalize-Cik([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    $digits = ($Value -replace '\D','')
    if (-not $digits) { return "" }
    return $digits.PadLeft(10,'0')
}

function Get-CurrentSecMap {
    $json = Invoke-SecGet "https://www.sec.gov/files/company_tickers.json" | ConvertFrom-Json
    $map = @{}
    foreach ($p in $json.PSObject.Properties) {
        $v = $p.Value
        $ticker = ([string]$v.ticker).Trim().ToUpperInvariant()
        $cik = Normalize-Cik ([string]$v.cik_str)
        if ($ticker -and $cik) { $map[$ticker] = $cik }
    }
    return $map
}

function Get-FilingRows([string]$Cik10) {
    $url = "https://data.sec.gov/submissions/CIK$Cik10.json"
    $obj = Invoke-SecGet $url | ConvertFrom-Json
    $rows = New-Object System.Collections.Generic.List[object]

    $recent = $obj.filings.recent
    if ($recent -and $recent.accessionNumber) {
        for ($i=0; $i -lt $recent.accessionNumber.Count; $i++) {
            $rows.Add([pscustomobject]@{
                accessionNumber = $recent.accessionNumber[$i]
                filingDate = $recent.filingDate[$i]
                form = $recent.form[$i]
                primaryDocument = $recent.primaryDocument[$i]
            })
        }
    }

    foreach ($f in @($obj.filings.files)) {
        if (-not $f.name) { continue }
        $older = Invoke-SecGet ("https://data.sec.gov/submissions/" + $f.name) | ConvertFrom-Json
        if (-not $older.accessionNumber) { continue }

        for ($i=0; $i -lt $older.accessionNumber.Count; $i++) {
            $rows.Add([pscustomobject]@{
                accessionNumber = $older.accessionNumber[$i]
                filingDate = $older.filingDate[$i]
                form = $older.form[$i]
                primaryDocument = $older.primaryDocument[$i]
            })
        }
    }
    return $rows
}

function Get-DocumentUrl([string]$Cik10, [string]$Accession, [string]$Primary) {
    $cikInt = [int64]$Cik10
    $acc = $Accession -replace '-',''
    return "https://www.sec.gov/Archives/edgar/data/$cikInt/$acc/$Primary"
}

function Test-ExplicitCommonEvidence {
    param(
        [Parameter(Mandatory=$true)][string]$Html,
        [Parameter(Mandatory=$true)][string]$Ticker
    )

    $text = [System.Net.WebUtility]::HtmlDecode(($Html -replace '(?is)<script.*?</script>|<style.*?</style>',' ' -replace '<[^>]+>',' ' -replace '\s+',' '))
    $tickerRx = "(?i)(?<![A-Z0-9\.])" + [regex]::Escape($Ticker) + "(?![A-Z0-9\.])"
    $commonRx = '(?i)\b(common\s+(stock|shares?)|ordinary\s+(shares?|stock)|class\s+[a-z0-9]+\s+common)\b'
    $badRx = '(?i)\b(preferred|warrant|option|restricted\s+stock\s+unit|\brsu\b|phantom|convertible)\b'

    foreach ($m in [regex]::Matches($text, $tickerRx)) {
        $start = [Math]::Max(0, $m.Index - 900)
        $len = [Math]::Min(1800 + $m.Length, $text.Length - $start)
        $window = $text.Substring($start, $len)

        foreach ($cm in [regex]::Matches($window, $commonRx)) {
            $s = [Math]::Max(0, $cm.Index - 120)
            $l = [Math]::Min($cm.Length + 240, $window.Length - $s)
            $around = $window.Substring($s, $l)
            if ($around -notmatch $badRx) {
                return [pscustomobject]@{
                    Match = $true
                    Snippet = ($around -replace '\s+',' ').Trim()
                }
            }
        }
    }

    # Inline XBRL fallback.
    $escaped = [regex]::Escape($Ticker)
    if ($Html -match "(?is)(TradingSymbol|dei:TradingSymbol)[^>]*>\s*$escaped\s*<") {
        $matches = [regex]::Matches($Html, '(?is)(Security12bTitle|dei:Security12bTitle)[^>]*>(.*?)<')
        foreach ($m in $matches) {
            $v = [System.Net.WebUtility]::HtmlDecode(($m.Groups[2].Value -replace '<[^>]+>',' ' -replace '\s+',' ')).Trim()
            if ($v -match $commonRx -and $v -notmatch $badRx) {
                return [pscustomobject]@{ Match=$true; Snippet=$v }
            }
        }
    }

    return [pscustomobject]@{ Match=$false; Snippet="" }
}

Write-Host "Loading SEC ticker map..."
$secMap = Get-CurrentSecMap

$gaps = Import-Csv $Gaps
$evidence = New-Object System.Collections.Generic.List[object]
$unresolved = New-Object System.Collections.Generic.List[object]
$cache = @{}

$i = 0
foreach ($g in $gaps) {
    $i++
    $ticker = ([string]$g.ticker).Trim().ToUpperInvariant()
    $buyDate = ([string]$g.buy_date).Trim()
    $cik = ""
    if ($secMap.ContainsKey($ticker)) { $cik = $secMap[$ticker] }

    $resolved = $false
    $lastError = ""

    if ($cik) {
        try {
            if (-not $cache.ContainsKey($cik)) {
                $cache[$cik] = @(Get-FilingRows $cik)
            }

            $eligible = @(
                $cache[$cik] |
                Where-Object {
                    ($Forms -contains $_.form) -and
                    $_.filingDate -and
                    ([string]$_.filingDate -lt $buyDate) -and
                    $_.accessionNumber -and
                    $_.primaryDocument
                } |
                Sort-Object filingDate -Descending |
                Select-Object -First 20
            )

            foreach ($f in $eligible) {
                $url = Get-DocumentUrl $cik ([string]$f.accessionNumber) ([string]$f.primaryDocument)
                try {
                    $html = Invoke-SecGet $url
                    $test = Test-ExplicitCommonEvidence -Html $html -Ticker $ticker
                    if ($test.Match) {
                        $evidence.Add([pscustomobject]@{
                            ticker = $ticker
                            buy_date = $buyDate
                            cik = $cik
                            cik_source = "current_sec_ticker_retrieval_hint"
                            filing_date = [string]$f.filingDate
                            form = [string]$f.form
                            accession = [string]$f.accessionNumber
                            primary_document = [string]$f.primaryDocument
                            evidence_strength = "explicit_symbol_plus_common_title"
                            security_title_snippet = $test.Snippet
                            source_url = $url
                        })
                        $resolved = $true
                        break
                    }
                }
                catch {
                    $lastError = $_.Exception.Message
                }
            }
        }
        catch {
            $lastError = $_.Exception.Message
        }
    }

    if (-not $resolved) {
        $unresolved.Add([pscustomobject]@{
            ticker = $ticker
            buy_date = $buyDate
            current_sec_map_cik = $cik
            last_error = $lastError
        })
    }

    if (($i % 10) -eq 0 -or $i -eq $gaps.Count) {
        Write-Host ("Processed {0}/{1} resolved={2} unresolved={3}" -f $i,$gaps.Count,$evidence.Count,$unresolved.Count)
    }
}

$evidence | Export-Csv -NoTypeInformation -Encoding UTF8 $Out
$unresolved | Export-Csv -NoTypeInformation -Encoding UTF8 $Unresolved

$reportObj = [ordered]@{
    input_gap_rows = $gaps.Count
    resolved_rows = $evidence.Count
    unresolved_rows = $unresolved.Count
    resolved_pct = if ($gaps.Count) { $evidence.Count / $gaps.Count } else { $null }
    method = "Targeted SEC EDGAR historical primary filings. Current SEC ticker mapping is retrieval-only; positive classification requires a filing strictly before the Orion buy date with explicit ticker plus common/ordinary-equity title."
    forms = $Forms
    unknown_policy = "unresolved remains unknown/ineligible"
    generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
}
$reportObj | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $Report

Write-Host ""
Write-Host "Completed."
Write-Host "Evidence:   $Out"
Write-Host "Unresolved: $Unresolved"
Write-Host "Report:     $Report"
Write-Host ""
Write-Host ("Resolved {0}/{1} ({2:P2})" -f $evidence.Count,$gaps.Count,($evidence.Count/[double][Math]::Max(1,$gaps.Count)))

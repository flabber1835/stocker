param(
  [string]$RepoRoot=".",
  [string]$UserAgent="Orion-PIT-research/3.0 your-real-email@example.com"
)

$ErrorActionPreference="Stop"
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
$PitDir=Join-Path $RepoRoot "PIT input data"
$GapsPath=Join-Path $PitDir "SEC_SECURITY_TYPE_BUY_COVERAGE_GAPS.csv"
$ManualPath=Join-Path $PitDir "SEC_SECURITY_TYPE_MANUAL_EDGAR_EVIDENCE.csv"
$EvidencePath=Join-Path $PitDir "SEC_COVERPAGE_SECURITY_TYPE_EVIDENCE.csv"
$UnresolvedPath=Join-Path $PitDir "SEC_COVERPAGE_SECURITY_TYPE_UNRESOLVED.csv"
$ReportPath=Join-Path $PitDir "SEC_COVERPAGE_SECURITY_TYPE_REPORT.json"

if(!(Test-Path -LiteralPath $GapsPath)){ throw "Missing input file: $GapsPath" }

$Headers=@{"User-Agent"=$UserAgent;"Accept-Encoding"="identity"}
$Forms=@("10-K","10-K/A","10-Q","10-Q/A","20-F","20-F/A","40-F","40-F/A","S-1","S-1/A","F-1","F-1/A","8-K","8-K/A","6-K","6-K/A","8-A","8-A12B","8-A12G","424B4","424B3","F-10","F-10/A","S-3","S-3/A")

function Get-Sec([string]$Url){
  for($i=1;$i -le 6;$i++){
    try{
      $r=Invoke-WebRequest -Uri $Url -Headers $Headers -UseBasicParsing -TimeoutSec 60
      Start-Sleep -Milliseconds 180
      return [string]$r.Content
    }catch{
      if($i -eq 6){ throw }
      Start-Sleep -Seconds ([Math]::Min(20,2*$i))
    }
  }
}

function Norm-Cik([string]$x){
  $d=$x -replace '\D',''
  if(!$d){ return "" }
  return $d.PadLeft(10,'0')
}

function Current-Sec-Map{
  $o=Get-Sec "https://www.sec.gov/files/company_tickers.json" | ConvertFrom-Json
  $m=@{}
  foreach($p in $o.PSObject.Properties){
    $t=([string]$p.Value.ticker).Trim().ToUpper()
    $c=Norm-Cik ([string]$p.Value.cik_str)
    if($t -and $c){$m[$t]=$c}
  }
  return $m
}

function Filing-Rows([string]$cik){
  $o=Get-Sec "https://data.sec.gov/submissions/CIK$cik.json" | ConvertFrom-Json
  $rows=@()
  $r=$o.filings.recent
  for($i=0;$r.accessionNumber -and $i -lt $r.accessionNumber.Count;$i++){
    $rows += [pscustomobject]@{accession=$r.accessionNumber[$i];date=$r.filingDate[$i];form=$r.form[$i];doc=$r.primaryDocument[$i]}
  }
  foreach($f in @($o.filings.files)){
    if(!$f.name){continue}
    $q=Get-Sec ("https://data.sec.gov/submissions/"+$f.name) | ConvertFrom-Json
    for($i=0;$q.accessionNumber -and $i -lt $q.accessionNumber.Count;$i++){
      $rows += [pscustomobject]@{accession=$q.accessionNumber[$i];date=$q.filingDate[$i];form=$q.form[$i];doc=$q.primaryDocument[$i]}
    }
  }
  return $rows
}

function Doc-Url([string]$cik,[string]$acc,[string]$doc){
  $ci=[int64]$cik
  $a=$acc -replace '-',''
  return "https://www.sec.gov/Archives/edgar/data/$ci/$a/$doc"
}

function Classify([string]$html,[string]$ticker){
  $text=[System.Net.WebUtility]::HtmlDecode(($html -replace '(?is)<script.*?</script>|<style.*?</style>',' ' -replace '<[^>]+>',' ' -replace '\s+',' '))
  $tr="(?i)(?<![A-Z0-9\.])"+[regex]::Escape($ticker)+"(?![A-Z0-9\.])"
  $common='(?i)\b(common\s+(stock|shares?)|ordinary\s+(shares?|stock)|class\s+[a-z0-9]+\s+common)\b'
  $adr='(?i)\b(ADR|ADS|American Depositary (Receipt|Share)s?)\b'
  $lp='(?i)\b(common\s+units?|limited\s+partner\s+interests?|partnership\s+units?)\b'
  foreach($m in [regex]::Matches($text,$tr)){
    $s=[Math]::Max(0,$m.Index-1200); $l=[Math]::Min(2400+$m.Length,$text.Length-$s); $w=$text.Substring($s,$l)
    if($w -match $lp){ return @("non_common_lp_unit",$w.Substring(0,[Math]::Min(600,$w.Length))) }
    if($w -match $adr -and $w -match $common){ return @("common_equity_adr",$w.Substring(0,[Math]::Min(600,$w.Length))) }
    if($w -match $common){ return @("common",$w.Substring(0,[Math]::Min(600,$w.Length))) }
  }
  return $null
}

Write-Host "Repo root: $RepoRoot"
Write-Host "Loading current SEC ticker map (retrieval hint only)..."
$secmap=Current-Sec-Map

$done=@{}
if(Test-Path -LiteralPath $ManualPath){
  Import-Csv -LiteralPath $ManualPath | ForEach-Object { if($_.orion_ticker -and $_.buy_date){$done["$($_.orion_ticker)|$($_.buy_date)"]=$true} }
}

$gaps=@(Import-Csv -LiteralPath $GapsPath)
$evidence=@(); $unresolved=@(); $cache=@{}
$i=0
foreach($g in $gaps){
  $i++
  $t=([string]$g.ticker).Trim().ToUpper(); $d=([string]$g.buy_date).Trim()
  if($done.ContainsKey("$t|$d")){ continue }
  $resolved=$false; $err=""; $cik=""
  if($secmap.ContainsKey($t)){ $cik=$secmap[$t] }
  if($cik){
    try{
      if(!$cache.ContainsKey($cik)){ $cache[$cik]=@(Filing-Rows $cik) }
      $cand=@($cache[$cik] | ? {($Forms -contains $_.form) -and $_.date -lt $d -and $_.accession -and $_.doc} | sort date -Descending | select -First 30)
      foreach($f in $cand){
        try{
          $u=Doc-Url $cik $f.accession $f.doc
          $cl=Classify (Get-Sec $u) $t
          if($cl){
            $evidence += [pscustomobject]@{ticker=$t;buy_date=$d;cik=$cik;cik_source="current_sec_ticker_retrieval_hint";filing_date=$f.date;form=$f.form;accession=$f.accession;primary_document=$f.doc;classification=$cl[0];evidence_strength="explicit_historical_filing";security_title_snippet=$cl[1];source_url=$u}
            $resolved=$true; break
          }
        }catch{$err=$_.Exception.Message}
      }
    }catch{$err=$_.Exception.Message}
  }
  if(!$resolved){
    $unresolved += [pscustomobject]@{ticker=$t;buy_date=$d;current_sec_map_cik=$cik;last_error=$err}
  }
  if(($i%10)-eq 0 -or $i -eq $gaps.Count){Write-Host "Processed $i/$($gaps.Count) manual_skips=$($done.Count) new_resolved=$($evidence.Count) new_unresolved=$($unresolved.Count)"}
}

$evidence | Export-Csv -LiteralPath $EvidencePath -NoTypeInformation -Encoding UTF8
$unresolved | Export-Csv -LiteralPath $UnresolvedPath -NoTypeInformation -Encoding UTF8

$report=[ordered]@{
  input_gap_rows=$gaps.Count
  manually_documented_rows_skipped=$done.Count
  newly_resolved_rows=$evidence.Count
  newly_unresolved_rows=$unresolved.Count
  method="Historical SEC filing must predate Orion buy. Current SEC ticker map is retrieval hint only."
  generated_at_utc=(Get-Date).ToUniversalTime().ToString("o")
}
[System.IO.File]::WriteAllText($ReportPath,(($report|ConvertTo-Json -Depth 4)+[Environment]::NewLine),[System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "Completed successfully."
Write-Host "Evidence:   $EvidencePath"
Write-Host "Unresolved: $UnresolvedPath"
Write-Host "Report:     $ReportPath"
Write-Host "Manual rows skipped: $($done.Count)"
Write-Host "Newly resolved: $($evidence.Count)"
Write-Host "Still unresolved: $($unresolved.Count)"

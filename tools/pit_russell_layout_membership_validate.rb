#!/usr/bin/env ruby
# frozen_string_literal: true

require 'csv'
require 'digest'
require 'fileutils'
require 'json'
require 'open3'
require 'optparse'
require 'tmpdir'

TICKER_RE = /\A[A-Z][A-Z0-9.\-]{0,9}\z/


def normalize(value)
  value.to_s.gsub("\u00A0", ' ').gsub(/\s+/, ' ').strip
end


def header_pairs(line)
  tokens = []
  line.to_enum(:scan, /\b(?:Company|Ticker|Symbol)\b/i).each do
    match = Regexp.last_match
    tokens << [match.begin(0), match[0].downcase]
  end

  pairs = []
  idx = 0
  while idx + 1 < tokens.length
    if tokens[idx][1] == 'company' && %w[ticker symbol].include?(tokens[idx + 1][1])
      pairs << [tokens[idx][0], tokens[idx + 1][0]]
      idx += 2
    else
      idx += 1
    end
  end
  pairs
end


def parse_layout_text(text)
  by_ticker = {}
  table_pages = 0

  text.split("\f", -1).each do |page|
    lines = page.lines.map { |line| line.delete_suffix("\n").delete_suffix("\r") }
    header_index = nil
    pairs = nil

    lines.each_with_index do |line, idx|
      candidate = header_pairs(line)
      next if candidate.empty?
      if pairs.nil? || candidate.length > pairs.length
        header_index = idx
        pairs = candidate
      end
    end

    next if pairs.nil? || pairs.empty?
    table_pages += 1

    lines[(header_index + 1)..].to_a.each do |line|
      pairs.each_with_index do |(company_start, ticker_start), pair_idx|
        next_company_start = pair_idx + 1 < pairs.length ? pairs[pair_idx + 1][0] : line.length
        next if company_start >= line.length || ticker_start >= line.length

        company = normalize(line[company_start...ticker_start])
        ticker = normalize(line[ticker_start...next_company_start]).upcase
        next if company.empty? || !TICKER_RE.match?(ticker)

        previous = by_ticker[ticker]
        if previous && previous != company
          raise "ambiguous layout ticker #{ticker}: #{previous.inspect} vs #{company.inspect}"
        end
        by_ticker[ticker] = company
      end
    end
  end

  [by_ticker, table_pages]
end


def render_layout(pdf_path)
  Dir.mktmpdir('russell-layout-') do |dir|
    text_path = File.join(dir, 'source.txt')
    stdout, stderr, status = Open3.capture3('pdftotext', '-layout', pdf_path, text_path)
    raise "pdftotext failed: #{stderr.strip} #{stdout.strip}" unless status.success?
    return File.binread(text_path).force_encoding('UTF-8').scrub
  end
end


def extract_pdf(pdf_path)
  parse_layout_text(render_layout(pdf_path))
end


def read_source_csv(path)
  by_ticker = {}
  CSV.foreach(path, headers: true, encoding: 'bom|utf-8') do |row|
    ticker = normalize(row['Ticker']).upcase
    company = normalize(row['Company'])
    next if ticker.empty?
    raise "invalid source CSV ticker #{ticker.inspect}" unless TICKER_RE.match?(ticker)

    previous = by_ticker[ticker]
    if previous && previous != company
      raise "ambiguous source CSV ticker #{ticker}: #{previous.inspect} vs #{company.inspect}"
    end
    by_ticker[ticker] = company
  end
  by_ticker
end


def rows_sha(rows)
  payload = rows.keys.sort.map { |ticker| "#{ticker}\t#{rows[ticker]}\n" }.join
  Digest::SHA256.hexdigest(payload)
end


def write_canonical_csv(path, source_rows)
  CSV.open(path, 'wb', row_sep: "\n") do |csv|
    csv << %w[ticker company]
    source_rows.keys.sort.each { |ticker| csv << [ticker, source_rows[ticker]] }
  end
  Digest::SHA256.file(path).hexdigest
end

options = {}
OptionParser.new do |parser|
  parser.on('--year YEAR', Integer) { |v| options[:year] = v }
  parser.on('--membership-date DATE') { |v| options[:membership_date] = v }
  parser.on('--pdf PATH') { |v| options[:pdf] = v }
  parser.on('--csv PATH') { |v| options[:csv] = v }
  parser.on('--output-dir PATH') { |v| options[:output_dir] = v }
  parser.on('--source-ref REF') { |v| options[:source_ref] = v }
  parser.on('--min-rows N', Integer) { |v| options[:min_rows] = v }
  parser.on('--max-rows N', Integer) { |v| options[:max_rows] = v }
end.parse!

%i[year membership_date pdf csv output_dir source_ref].each do |key|
  raise "missing --#{key.to_s.tr('_', '-')}" unless options[key]
end
options[:min_rows] ||= 2800
options[:max_rows] ||= 3200

FileUtils.mkdir_p(options[:output_dir])
pdf_rows_1, table_pages_1 = extract_pdf(options[:pdf])
pdf_rows_2, table_pages_2 = extract_pdf(options[:pdf])
source_rows = read_source_csv(options[:csv])

pdf_tickers = pdf_rows_1.keys.sort
source_tickers = source_rows.keys.sort
missing_from_pdf = source_tickers - pdf_tickers
missing_from_csv = pdf_tickers - source_tickers
layout_sha_1 = rows_sha(pdf_rows_1)
layout_sha_2 = rows_sha(pdf_rows_2)
deterministic = pdf_rows_1 == pdf_rows_2 && layout_sha_1 == layout_sha_2 && table_pages_1 == table_pages_2
count_ok = options[:min_rows] <= pdf_tickers.length && pdf_tickers.length <= options[:max_rows]
membership_ok = missing_from_pdf.empty? && missing_from_csv.empty?

company_mismatches = pdf_tickers.filter_map do |ticker|
  next unless source_rows.key?(ticker)
  next if normalize(pdf_rows_1[ticker]).casecmp?(normalize(source_rows[ticker]))
  {
    'ticker' => ticker,
    'pdf_company' => pdf_rows_1[ticker],
    'csv_company' => source_rows[ticker]
  }
end

canonical_path = File.join(options[:output_dir], "russell3000_#{options[:year]}.csv")
canonical_sha = write_canonical_csv(canonical_path, source_rows)

result = {
  'schema' => 1,
  'year' => options[:year],
  'membership_date' => options[:membership_date],
  'membership_date_basis' => 'date encoded by preserved Russell membership-list source filename',
  'pit_effective_boundary_status' => 'NOT_YET_CERTIFIED',
  'source_repository' => 'kact998/Russell3000Components',
  'source_repository_ref' => options[:source_ref],
  'source_pdf_sha256' => Digest::SHA256.file(options[:pdf]).hexdigest,
  'source_pdf_bytes' => File.size(options[:pdf]),
  'source_csv_sha256' => Digest::SHA256.file(options[:csv]).hexdigest,
  'extractor_contract' => 'poppler_layout_header_sliced_ruby_v1',
  'table_pages' => table_pages_1,
  'row_count' => pdf_tickers.length,
  'unique_tickers' => pdf_tickers.length,
  'layout_rows_sha256' => layout_sha_1,
  'canonical_csv_sha256' => canonical_sha,
  'count_gate' => count_ok ? 'PASS' : 'FAIL',
  'determinism_gate' => deterministic ? 'PASS' : 'FAIL',
  'pdf_csv_membership_gate' => membership_ok ? 'PASS' : 'FAIL',
  'missing_from_pdf' => missing_from_pdf,
  'missing_from_csv' => missing_from_csv,
  'company_label_mismatch_count' => company_mismatches.length,
  'company_label_mismatches' => company_mismatches,
  'evidence_grade' => count_ok && deterministic && membership_ok ? 'A_SOURCE_MEMBERSHIP' : 'UNACCEPTED'
}

File.write(File.join(options[:output_dir], 'manifest.json'), JSON.pretty_generate(result) + "\n")
puts JSON.generate(result)
exit(count_ok && deterministic && membership_ok ? 0 : 2)

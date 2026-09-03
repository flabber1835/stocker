# frozen_string_literal: true

require 'minitest/autorun'

SCRIPT = File.expand_path('../../tools/pit_russell_layout_membership_validate.rb', __dir__)
source = File.read(SCRIPT)
loader = source.split("options = {}", 2).first
TOPLEVEL_BINDING.eval(loader, SCRIPT)

class RussellLayoutMembershipValidateTest < Minitest::Test
  def test_header_sliced_parser_accepts_short_all_caps_companies_and_ltd_ticker
    text = <<~TEXT
      Russell 3000 Membership List
      Company                       Ticker    Company                       Ticker
      AUTONATION INC                AN        INTUIT                        INTU
      LIMITED BRANDS INC            LTD       SOTHEBYS                      BID
      PROLOGIS                      PLD       AMERCO                        UHAL
      tax legal prose               NT        more lower prose              IOR
      \f
      Important information
      tax, securities, or investment advice, nor AN
    TEXT

    rows, pages = parse_layout_text(text)
    assert_equal 1, pages
    assert_equal 'AUTONATION INC', rows['AN']
    assert_equal 'INTUIT', rows['INTU']
    assert_equal 'LIMITED BRANDS INC', rows['LTD']
    assert_equal 'SOTHEBYS', rows['BID']
    assert_equal 'PROLOGIS', rows['PLD']
    assert_equal 'AMERCO', rows['UHAL']
    refute rows.key?('NT')
    refute rows.key?('IOR')
    assert_equal 6, rows.length
  end

  def test_page_without_company_ticker_header_is_ignored
    text = "Disclaimer text with AN and KEY and PLD\n"
    rows, pages = parse_layout_text(text)
    assert_empty rows
    assert_equal 0, pages
  end
end

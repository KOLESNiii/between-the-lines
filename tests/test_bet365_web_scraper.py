from bet365_web_scraper import (
    Bet365RenderedPageScraper,
    Bet365WebScraper,
    EndpointResult,
    Match,
    fixture_market_topics,
    fixture_rendered_market_topics,
    fixture_rendered_tab_topics,
    parse_bet365_market_group_dom_items,
    parse_cards_dom_items,
    parse_corners_dom_items,
    parse_full_time_result_dom_items,
    parse_goals_dom_items,
    parse_matches,
    parse_player_props_dom_items,
    parse_shots_dom_items,
    parse_visible_odds_text,
    direct_discovery_topics,
    strip_match_odds,
)


def _payload_with_prebuilt_and_player_markets():
    return "\x08".join(
        [
            "F|MG;ID=M181449;NA=Player / Last 5;SY=pmm;|"
            "MA;ID=M2660;NA=Harrison Barnes;PD=#NBA#P2660#;|"
            "PA;ID=old-price;MA=181449;NA=1;FI=999;PF=999;OD=13/10;|",
            "F|PA;FI=192;PD=#AC#B1#C1#D8#E192#F3#I1#P28778#H1#;"
            "BC=20260511200000;NA=Tottenham;N2=Leeds;L3=FA Barclaycard;|",
            "F|MG;L3=FA Barclaycard;MA=40;PF=192;NA=Tottenham v Leeds;SY=pbd;"
            "OD=16/1;CH=Too Big To Go Down?;|"
            "MA;ID=998;MA=40;NA=FT Result: Tottenham;FI=192;OI=192;OD=4/5;|",
            "F|MG;MA=40;OI=192;SY=cpmg;|"
            "MA;ID=40;NA= ;FI=192;SY=cpma;|"
            "MA;ID=CL0;MA=40;NA=1;FI=192;SY=cpce;|"
            "PA;ID=998;FI=192;OI=192;OD=4/5;|"
            "MA;ID=CL0;MA=40;NA=X;FI=192;SY=cpce;|"
            "PA;ID=999;FI=192;OI=192;OD=29/10;|",
            "F|MA;ID=M64;NA=Player / Last 5;FI=192;PF=192;SY=phs;|"
            "PA;ID=PC64;NA=Dominic Calvert-Lewin;OR=2;"
            "PD=#AC#B1#C1#D1002#E91422157#G99#P653118#;|"
            "CO;ID=C64;MA=64;NA=To Score;FI=192;PF=192;SY=pot;|"
            "PA;ID=score-price;FI=192;PF=192;OD=2/1;OR=2;|",
            "F|MG;ID=M50538;NA=Player / Last 5;SY=pmm;|"
            "MA;ID=M653118;NA=Dominic Calvert-Lewin;"
            "PD=#AC#B1#C1#D1002#E91422157#G99#P653118#;|"
            "PA;ID=sot-price;MA=50538;NA=1+;FI=192;PF=192;OD=4/7;|",
        ]
    )


def test_parse_match_odds_defaults_to_main_markets_only():
    [match] = parse_matches(_payload_with_prebuilt_and_player_markets())
    selections = {(selection.name, selection.odds, selection.market) for selection in match.odds}

    assert selections == {
        ("Tottenham", "4/5", "Full Time Result"),
        ("Draw", "29/10", "Full Time Result"),
    }
    assert not any(selection.name.startswith("Harrison Barnes") for selection in match.odds)


def test_parse_match_odds_can_include_player_props_without_leaking_context():
    [match] = parse_matches(_payload_with_prebuilt_and_player_markets(), include_player_props=True)
    selections = {(selection.name, selection.odds, selection.market) for selection in match.odds}

    assert ("Tottenham", "4/5", "Full Time Result") in selections
    assert ("Draw", "29/10", "Full Time Result") in selections
    assert ("Dominic Calvert-Lewin", "2/1", "To Score") in selections
    assert ("Dominic Calvert-Lewin: 1+", "4/7", "Player Shots on Target") in selections
    assert not any(selection.name.startswith("Harrison Barnes") for selection in match.odds)


def test_parse_match_odds_can_include_prebuilt_bets_explicitly():
    payload = "\x08".join(
        [
            "F|PA;FI=192;PD=#AC#B1#C1#D8#E192#F3#I1#P28778#H1#;"
            "BC=20260511200000;NA=Tottenham;N2=Leeds;L3=FA Barclaycard;|",
            "F|MG;L3=FA Barclaycard;MA=40;PF=192;NA=Tottenham v Leeds;SY=pbd;"
            "OD=16/1;CH=Too Big To Go Down?;|"
            "MA;ID=998;MA=40;NA=FT Result: Tottenham;FI=192;OI=192;OD=4/5;|",
        ]
    )

    [match] = parse_matches(payload, include_prebuilt_bets=True)
    selections = {(selection.name, selection.odds, selection.market) for selection in match.odds}

    assert ("Too Big To Go Down?", "16/1", "Full Time Result") in selections
    assert ("Tottenham", "4/5", "Full Time Result") in selections


def test_parse_match_page_market_rows_inherit_fixture_from_market_header():
    payload = "|".join(
        [
            "PA;FI=192;PD=%23AC%23B1%23C1%23D8%23E192%23F3%23I1%23P28778%23H1%23;"
            "BC=20260511200000;NA=Tottenham;N2=Leeds;L3=FA%20Barclaycard",
            "MG;ID=10150;SY=mgi;NA=Both%20Teams%20To%20Score;DO=1;PD=;BW=1;FF=IA",
            "MA;ID=M10150;FI=192;PF=192;CN=3;CX=1;SY=_a;PY=_f;MA=10150;FF=IA",
            "PA;ID=yes-price;NA=Yes;SU=0;OD=4/6;FF=IA",
            "PA;ID=no-price;NA=No;SU=0;OD=11/10;FF=IA",
        ]
    )

    [match] = parse_matches(payload)

    assert [(odd.market_code, odd.market, odd.name, odd.odds) for odd in match.odds] == [
        ("10150", "Both Teams to Score", "Yes", "4/6"),
        ("10150", "Both Teams to Score", "No", "11/10"),
    ]


def test_fixture_market_topics_use_match_id_f4_through_f9():
    match = Match(fixture_id="192", home="Tottenham", away="Leeds")

    assert fixture_market_topics(match) == [
        ("fixture_f4", "#AC#B1#C1#D8#E192#F3#F4#"),
        ("fixture_f5", "#AC#B1#C1#D8#E192#F3#F5#"),
        ("fixture_f6", "#AC#B1#C1#D8#E192#F3#F6#"),
        ("fixture_f7", "#AC#B1#C1#D8#E192#F3#F7#"),
        ("fixture_f8", "#AC#B1#C1#D8#E192#F3#F8#"),
        ("fixture_f9", "#AC#B1#C1#D8#E192#F3#F9#"),
    ]


def test_fixture_market_topics_ignore_discovered_page_suffix():
    match = Match(
        fixture_id="192",
        home="Tottenham",
        away="Leeds",
        page_data="#AC#B1#C1#D8#E192#F3#I1#P31524#H1#",
    )

    assert fixture_market_topics(match) == [
        ("fixture_f4", "#AC#B1#C1#D8#E192#F3#F4#"),
        ("fixture_f5", "#AC#B1#C1#D8#E192#F3#F5#"),
        ("fixture_f6", "#AC#B1#C1#D8#E192#F3#F6#"),
        ("fixture_f7", "#AC#B1#C1#D8#E192#F3#F7#"),
        ("fixture_f8", "#AC#B1#C1#D8#E192#F3#F8#"),
        ("fixture_f9", "#AC#B1#C1#D8#E192#F3#F9#"),
    ]


def test_fixture_rendered_tab_topics_use_match_id_i4_through_i9_without_page_suffix():
    match = Match(
        fixture_id="192",
        home="Tottenham",
        away="Leeds",
        page_data="#AC#B1#C1#D8#E192#F3#I1#P31524#H1#",
    )

    assert fixture_rendered_tab_topics(match) == [
        ("fixture_i4", "#AC#B1#C1#D8#E192#F3#I4#"),
        ("fixture_i5", "#AC#B1#C1#D8#E192#F3#I5#"),
        ("fixture_i6", "#AC#B1#C1#D8#E192#F3#I6#"),
        ("fixture_i7", "#AC#B1#C1#D8#E192#F3#I7#"),
        ("fixture_i8", "#AC#B1#C1#D8#E192#F3#I8#"),
        ("fixture_i9", "#AC#B1#C1#D8#E192#F3#I9#"),
    ]


def test_fixture_rendered_market_topics_use_i1_for_full_time_result():
    match = Match(
        fixture_id="192",
        home="Tottenham",
        away="Leeds",
        page_data="#AC#B1#C1#D8#E192#F3#I4#P31524#H1#",
    )

    assert fixture_rendered_market_topics(match) == [
        ("full_time_result_i1", "#AC#B1#C1#D8#E192#F3#I1#"),
        ("cards_i4", "#AC#B1#C1#D8#E192#F3#I4#"),
        ("corners_i5", "#AC#B1#C1#D8#E192#F3#I5#"),
        ("goals_i6", "#AC#B1#C1#D8#E192#F3#I6#"),
        ("player_props_i8", "#AC#B1#C1#D8#E192#F3#I8#"),
        ("shots_i9", "#AC#B1#C1#D8#E192#F3#I9#"),
    ]


def test_parse_market_topic_can_attach_to_known_fixture_without_fixture_header():
    payload = "|".join(
        [
            "MG;ID=10150;SY=mgi;NA=Both%20Teams%20To%20Score;DO=1;PD=;BW=1;FF=IA",
            "MA;ID=M10150;FI=192;PF=192;CN=3;CX=1;SY=_a;PY=_f;MA=10150;FF=IA",
            "PA;ID=yes-price;NA=Yes;SU=0;OD=4/6;FF=IA",
            "PA;ID=no-price;NA=No;SU=0;OD=11/10;FF=IA",
        ]
    )
    known_match = Match(fixture_id="192", home="Tottenham", away="Leeds")

    [match] = parse_matches(payload, known_matches=[known_match])

    assert [(odd.market_code, odd.market, odd.name, odd.odds) for odd in match.odds] == [
        ("10150", "Both Teams to Score", "Yes", "4/6"),
        ("10150", "Both Teams to Score", "No", "11/10"),
    ]


def test_parse_visible_odds_text_reads_rendered_main_market_lines():
    match = Match(fixture_id="192", home="Tottenham", away="Leeds")
    text = "\n".join(
        [
            "Full Time Result",
            "1",
            "3/4",
            "X",
            "29/10",
            "2",
            "10/3",
            "Bet Builder",
            "Named Boost",
            "16/1",
        ]
    )

    selections = parse_visible_odds_text(text, match)

    assert [(selection.market, selection.name, selection.odds) for selection in selections] == [
        ("Full Time Result", "Tottenham", "3/4"),
        ("Full Time Result", "Draw", "29/10"),
        ("Full Time Result", "Leeds", "10/3"),
    ]


def test_parse_bet365_market_group_dom_items_reads_market_group_participants():
    match = Match(fixture_id="192", home="Tottenham", away="Leeds")
    items = [
        {"market": "First Set Piece (00:00 - 04:59)", "name": "Throw In", "odds": "8/15"},
        {"market": "First Set Piece (00:00 - 04:59)", "name": "Free Kick", "odds": "10/3"},
        {"market": "First Set Piece (00:00 - 04:59)", "name": "Goal Kick", "odds": "6/1"},
        {"market": "First Set Piece (00:00 - 04:59)", "name": "Corner", "odds": "12/1"},
        {"market": "First Set Piece (00:00 - 04:59)", "name": "Penalty Awarded", "odds": "100/1"},
        {"market": "First Set Piece (00:00 - 04:59)", "name": "No Set Piece", "odds": "50/1"},
    ]

    selections = parse_bet365_market_group_dom_items(items, match)

    assert [(selection.market, selection.name, selection.odds) for selection in selections] == [
        ("First Set Piece (00:00 - 04:59)", "Throw In", "8/15"),
        ("First Set Piece (00:00 - 04:59)", "Free Kick", "10/3"),
        ("First Set Piece (00:00 - 04:59)", "Goal Kick", "6/1"),
        ("First Set Piece (00:00 - 04:59)", "Corner", "12/1"),
        ("First Set Piece (00:00 - 04:59)", "Penalty Awarded", "100/1"),
        ("First Set Piece (00:00 - 04:59)", "No Set Piece", "50/1"),
    ]


def test_parse_full_time_result_dom_items_reads_standard_three_way_layout_and_enhanced_prices():
    match = Match(fixture_id="192", home="Tottenham", away="Leeds")
    items = [
        {"market": "Full Time Result", "name": "Tottenham", "odds": "3/4"},
        {"market": "Full Time Result", "name": "Draw", "odds": "29/10"},
        {"market": "Full Time Result", "name": "Leeds", "odds": "7/2"},
        {"market": "Full Time Result - Enhanced", "name": "Tottenham", "odds": "4/5"},
        {"market": "Full Time Result - Enhanced", "name": "Draw", "odds": "3/1"},
        {"market": "Full Time Result - Enhanced", "name": "Leeds", "odds": "4/1"},
        {"market": "Full Time Result", "name": "4.5", "odds": "10/11"},
        {"market": "Number of Cards In Match BB", "name": "Over", "odds": "4.5"},
    ]

    selections = parse_full_time_result_dom_items(items, match)

    assert [(selection.market_code, selection.market, selection.name, selection.odds, selection.line) for selection in selections] == [
        ("40", "Full Time Result", "Tottenham", "3/4", None),
        ("40", "Full Time Result", "Draw", "29/10", None),
        ("40", "Full Time Result", "Leeds", "7/2", None),
        ("40", "Full Time Result - Enhanced", "Tottenham", "4/5", None),
        ("40", "Full Time Result - Enhanced", "Draw", "3/1", None),
        ("40", "Full Time Result - Enhanced", "Leeds", "4/1", None),
    ]


def test_parse_goals_dom_items_reads_total_goals_and_btts():
    match = Match(fixture_id="192", home="Tottenham", away="Leeds")
    items = [
        {"market": "Goals Over/Under", "line": "2.5", "name": "Over", "odds": "4/5"},
        {"market": "Goals Over/Under", "line": "2.5", "name": "Under", "odds": "1/1"},
        {"market": "Alternative Total Goals", "line": "0.5", "name": "Over", "odds": "1/20"},
        {"market": "Alternative Total Goals", "line": "0.5", "name": "Under", "odds": "10/1"},
        {"market": "Alternative Total Goals", "line": "4.5", "name": "Over", "odds": "9/2"},
        {"market": "Alternative Total Goals", "line": "4.5", "name": "Under", "odds": "1/7"},
        {"market": "Both Teams To Score", "name": "Yes", "odds": "3/4"},
        {"market": "Both Teams To Score", "name": "No", "odds": "1/1"},
        {"market": "Goals Over/Under", "line": "", "name": "Over", "odds": "4.5"},
        {"market": "Corners", "line": "2.5", "name": "Over", "odds": "4/5"},
    ]

    selections = parse_goals_dom_items(items, match)

    assert [(selection.market_code, selection.market, selection.name, selection.odds, selection.line) for selection in selections] == [
        (None, "Goals Over/Under 2.5", "Over", "4/5", "2.5"),
        (None, "Goals Over/Under 2.5", "Under", "1/1", "2.5"),
        (None, "Alternative Total Goals 0.5", "Over", "1/20", "0.5"),
        (None, "Alternative Total Goals 0.5", "Under", "10/1", "0.5"),
        (None, "Alternative Total Goals 4.5", "Over", "9/2", "4.5"),
        (None, "Alternative Total Goals 4.5", "Under", "1/7", "4.5"),
        ("10150", "Both Teams To Score", "Yes", "3/4", None),
        ("10150", "Both Teams To Score", "No", "1/1", None),
    ]


def test_parse_corners_dom_items_reads_three_way_two_way_and_race_grids():
    match = Match(fixture_id="192", home="Bournemouth", away="Man City")
    items = [
        {"market": "Corners", "line": "11", "name": "Over", "odds": "11/8"},
        {"market": "Corners", "line": "11", "name": "Exactly", "odds": "15/2"},
        {"market": "Corners", "line": "11", "name": "Under", "odds": "5/6"},
        {"market": "Alternative Corners", "line": "5", "name": "Over", "odds": "1/33"},
        {"market": "Alternative Corners", "line": "5", "name": "Exactly", "odds": "18/1"},
        {"market": "Alternative Corners", "line": "5", "name": "Under", "odds": "22/1"},
        {"market": "Corners 2-Way", "line": "10.5", "name": "Over", "odds": "5/6"},
        {"market": "Corners 2-Way", "line": "10.5", "name": "Under", "odds": "5/6"},
        {"market": "Corners Race", "line": "3", "name": "Bournemouth", "odds": "7/4"},
        {"market": "Corners Race", "line": "3", "name": "Man City", "odds": "2/5"},
        {"market": "Corners Race", "line": "3", "name": "Neither", "odds": "50/1"},
        {"market": "Corners", "line": "", "name": "Over", "odds": "11/8"},
        {"market": "Corners Race", "line": "3", "name": "Draw", "odds": "50/1"},
        {"market": "Goals Over/Under", "line": "2.5", "name": "Over", "odds": "4/5"},
    ]

    selections = parse_corners_dom_items(items, match)

    assert [(selection.market, selection.name, selection.odds, selection.line) for selection in selections] == [
        ("Corners 11", "Over", "11/8", "11"),
        ("Corners 11", "Exactly", "15/2", "11"),
        ("Corners 11", "Under", "5/6", "11"),
        ("Alternative Corners 5", "Over", "1/33", "5"),
        ("Alternative Corners 5", "Exactly", "18/1", "5"),
        ("Alternative Corners 5", "Under", "22/1", "5"),
        ("Corners 2-Way 10.5", "Over", "5/6", "10.5"),
        ("Corners 2-Way 10.5", "Under", "5/6", "10.5"),
        ("Corners Race 3", "Bournemouth", "7/4", "3"),
        ("Corners Race 3", "Man City", "2/5", "3"),
        ("Corners Race 3", "Neither", "50/1", "3"),
    ]


def test_parse_cards_dom_items_reads_total_cards_and_both_teams_to_receive_cards():
    match = Match(fixture_id="192", home="Bournemouth", away="Man City")
    items = [
        {"market": "Number Of Cards In Match", "line": "4.5", "name": "Over", "odds": "1/1"},
        {"market": "Number Of Cards In Match", "line": "4.5", "name": "Under", "odds": "8/11"},
        {"market": "Both Teams to Receive Cards", "line": "a Card", "name": "Yes", "odds": "1/5"},
        {"market": "Both Teams to Receive Cards", "line": "a Card", "name": "No", "odds": "10/3"},
        {"market": "Both Teams to Receive Cards", "line": "2+ Cards", "name": "Yes", "odds": "1/1"},
        {"market": "Both Teams to Receive Cards", "line": "2+ Cards", "name": "No", "odds": "8/11"},
        {"market": "Both Teams to Receive Cards", "line": "a Red Card", "name": "Yes", "odds": "66/1"},
        {"market": "Both Teams to Receive Cards", "line": "a Red Card", "name": "No", "odds": "1/750"},
        {"market": "Number Of Cards In Match", "line": "4.5", "name": "Exactly", "odds": "10/1"},
        {"market": "Number Of Cards In Match", "line": "Cards", "name": "Over", "odds": "1/1"},
        {"market": "Both Teams to Receive Cards", "line": "a Card", "name": "Maybe", "odds": "2/1"},
        {"market": "Corners", "line": "10.5", "name": "Over", "odds": "5/6"},
    ]

    selections = parse_cards_dom_items(items, match)

    assert [(selection.market, selection.name, selection.odds, selection.line) for selection in selections] == [
        ("Number Of Cards In Match 4.5", "Over", "1/1", "4.5"),
        ("Number Of Cards In Match 4.5", "Under", "8/11", "4.5"),
        ("Both Teams to Receive Cards a Card", "Yes", "1/5", "a Card"),
        ("Both Teams to Receive Cards a Card", "No", "10/3", "a Card"),
        ("Both Teams to Receive Cards 2+ Cards", "Yes", "1/1", "2+ Cards"),
        ("Both Teams to Receive Cards 2+ Cards", "No", "8/11", "2+ Cards"),
        ("Both Teams to Receive Cards a Red Card", "Yes", "66/1", "a Red Card"),
        ("Both Teams to Receive Cards a Red Card", "No", "1/750", "a Red Card"),
    ]


def test_parse_shots_dom_items_reads_match_and_team_shots_markets():
    match = Match(fixture_id="192", home="Bournemouth", away="Man City")
    items = [
        {"market": "Match Shots On Target", "line": "9.5", "name": "Over", "odds": "1/1"},
        {"market": "Match Shots On Target", "line": "9.5", "name": "Under", "odds": "8/11"},
        {"market": "Match Shots", "line": "26.5", "name": "Over", "odds": "1/1"},
        {"market": "Match Shots", "line": "26.5", "name": "Under", "odds": "8/11"},
        {"market": "Team Shots on Target", "line": "3.5", "name": "Over", "odds": "5/6", "context": "Bournemouth"},
        {"market": "Team Shots on Target", "line": "3.5", "name": "Under", "odds": "5/6", "context": "Bournemouth"},
        {"market": "Team Shots on Target", "line": "5.5", "name": "Over", "odds": "10/11", "context": "Man City"},
        {"market": "Team Shots on Target", "line": "5.5", "name": "Under", "odds": "4/5", "context": "Man City"},
        {"market": "Team Shots", "line": "11.5", "name": "Over", "odds": "1/1", "context": "Bournemouth"},
        {"market": "Team Shots", "line": "11.5", "name": "Under", "odds": "8/11", "context": "Bournemouth"},
        {"market": "Team Shots", "line": "14.5", "name": "Over", "odds": "5/6", "context": "Man City"},
        {"market": "Team Shots", "line": "14.5", "name": "Under", "odds": "5/6", "context": "Man City"},
        {"market": "Team Shots", "line": "14.5", "name": "Over", "odds": "5/6", "context": "Spurs"},
        {"market": "Match Shots", "line": "26.5", "name": "Exactly", "odds": "10/1"},
        {"market": "Corners", "line": "10.5", "name": "Over", "odds": "5/6"},
    ]

    selections = parse_shots_dom_items(items, match)

    assert [(selection.market, selection.name, selection.odds, selection.line) for selection in selections] == [
        ("Match Shots On Target 9.5", "Over", "1/1", "9.5"),
        ("Match Shots On Target 9.5", "Under", "8/11", "9.5"),
        ("Match Shots 26.5", "Over", "1/1", "26.5"),
        ("Match Shots 26.5", "Under", "8/11", "26.5"),
        ("Bournemouth Team Shots on Target 3.5", "Over", "5/6", "3.5"),
        ("Bournemouth Team Shots on Target 3.5", "Under", "5/6", "3.5"),
        ("Man City Team Shots on Target 5.5", "Over", "10/11", "5.5"),
        ("Man City Team Shots on Target 5.5", "Under", "4/5", "5.5"),
        ("Bournemouth Team Shots 11.5", "Over", "1/1", "11.5"),
        ("Bournemouth Team Shots 11.5", "Under", "8/11", "11.5"),
        ("Man City Team Shots 14.5", "Over", "5/6", "14.5"),
        ("Man City Team Shots 14.5", "Under", "5/6", "14.5"),
    ]


def test_parse_player_props_dom_items_reads_score_assist_and_shots_line_grids():
    match = Match(fixture_id="192", home="Bournemouth", away="Man City")
    items = [
        {"market": "Player to Score or Assist", "name": "Erling Haaland", "context": "Score", "odds": "8/15"},
        {"market": "Player to Score or Assist", "name": "Erling Haaland", "context": "Assist", "odds": "5/1"},
        {"market": "Player to Score or Assist", "name": "Erling Haaland", "context": "Score or Assist", "odds": "4/11"},
        {"market": "Player to Score or Assist", "name": "Rayan Cherki", "context": "Score", "odds": "7/4"},
        {"market": "Player Shots On Target", "name": "Erling Haaland", "line": "0.5", "odds": "1/6"},
        {"market": "Player Shots On Target", "name": "Erling Haaland", "line": "1.5", "odds": "4/5"},
        {"market": "Player Shots On Target", "name": "Rayan Cherki", "line": "0.5", "odds": "1/4"},
        {"market": "Player Shots", "name": "Erling Haaland", "line": "0.5", "odds": "1/66"},
        {"market": "Player Shots", "name": "Erling Haaland", "line": "1.5", "odds": "1/9"},
        {"market": "Player Shots", "name": "Rayan Cherki", "line": "0.5", "odds": "1/50"},
        {"market": "Player to Score or Assist", "name": "Erling Haaland", "context": "Tackle", "odds": "2/1"},
        {"market": "Player Shots", "name": "Rayan Cherki", "line": "", "odds": "1/50"},
        {"market": "Player Shots", "name": "Rayan Cherki", "line": "0.5", "odds": ""},
        {"market": "Corners", "name": "Over", "line": "10.5", "odds": "5/6"},
    ]

    selections = parse_player_props_dom_items(items, match)

    assert [(selection.market, selection.name, selection.odds, selection.line) for selection in selections] == [
        ("Player to Score", "Erling Haaland", "8/15", None),
        ("Player to Assist", "Erling Haaland", "5/1", None),
        ("Player Score or Assist", "Erling Haaland", "4/11", None),
        ("Player to Score", "Rayan Cherki", "7/4", None),
        ("Player Shots On Target 0.5", "Erling Haaland", "1/6", "0.5"),
        ("Player Shots On Target 1.5", "Erling Haaland", "4/5", "1.5"),
        ("Player Shots On Target 0.5", "Rayan Cherki", "1/4", "0.5"),
        ("Player Shots 0.5", "Erling Haaland", "1/66", "0.5"),
        ("Player Shots 1.5", "Erling Haaland", "1/9", "1.5"),
        ("Player Shots 0.5", "Rayan Cherki", "1/50", "0.5"),
    ]


def test_strip_match_odds_removes_homepage_prices_but_keeps_fixture_metadata():
    match = Match(
        fixture_id="192",
        home="Tottenham",
        away="Leeds",
        start_time="2026-05-11T20:00:00",
        competition="Premier League",
        page_data="#AC#B1#C1#D8#E192#F3#I1#",
        url="https://www.bet365.com/#/AC/B1/C1/D8/E192/F3/I1/",
    )
    match.odds.append(
        parse_full_time_result_dom_items(
            [{"market": "Full Time Result", "name": "Tottenham", "odds": "3/4"}],
            match,
        )[0]
    )

    [stripped] = strip_match_odds([match])

    assert stripped.fixture_id == "192"
    assert stripped.home == "Tottenham"
    assert stripped.away == "Leeds"
    assert stripped.start_time == "2026-05-11T20:00:00"
    assert stripped.competition == "Premier League"
    assert stripped.page_data == "#AC#B1#C1#D8#E192#F3#I1#"
    assert stripped.url == "https://www.bet365.com/#/AC/B1/C1/D8/E192/F3/I1/"
    assert stripped.odds == []


def test_match_markets_url_encodes_page_data_as_query_parameter():
    scraper = Bet365WebScraper()

    url = scraper._build_match_markets_url("#AC#B1#C1#D1002#E91422157#G40#")

    assert url.startswith("https://www.bet365.com/contentdata/matchmarketscontentapi/markets?")
    assert "pd=%23AC%23B1%23C1%23D1002%23E91422157%23G40%23" in url
    assert "cid=197" in url
    assert "cgid=2" in url
    assert "ctid=197" in url


def test_direct_discovery_topics_can_read_copied_contentdata_url(monkeypatch):
    monkeypatch.setenv(
        "BET365_DISCOVERY_TOPICS",
        "https://www.bet365.com/contentdata/matchmarketscontentapi/markets?"
        "lid=1&zid=1&pd=%23AC%23B1%23C1%23D1002%23E91422157%23G40%23&cid=197",
    )

    assert direct_discovery_topics() == ("#AC#B1#C1#D1002#E91422157#G40#",)


def test_rendered_network_payload_discovery_reads_fixture_ids_without_dom_links():
    payload = "|".join(
        [
            "PA;FI=192;PD=%23AC%23B1%23C1%23D8%23E192%23F3%23I1%23;"
            "BC=20260511200000;NA=Tottenham;N2=Leeds;L3=Premier%20League",
            "PA;FI=193;PD=%23AC%23B1%23C1%23D8%23E193%23F3%23I1%23;"
            "BC=20260511200000;NA=Everton;N2=Sunderland;L3=Premier%20League",
            "PA;FI=999;PD=%23AC%23B1%23C1%23D8%23E999%23F3%23I1%23;"
            "BC=20260511200000;NA=Barcelona;N2=Real%20Madrid;L3=La%20Liga",
        ]
    )
    result = EndpointResult(
        url="https://www.bet365.com/contentdata/matchmarketscontentapi/markets",
        status_code=200,
        bytes=len(payload),
        body=payload,
        source="rendered_network_contentdata",
    )

    matches = Bet365RenderedPageScraper._premier_league_matches_from_results(
        [result],
        {"tottenham", "leeds", "everton", "sunderland"},
    )

    assert [(match.fixture_id, match.home, match.away) for match in matches] == [
        ("192", "Tottenham", "Leeds"),
        ("193", "Everton", "Sunderland"),
    ]

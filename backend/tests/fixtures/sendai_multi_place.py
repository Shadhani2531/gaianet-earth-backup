"""
GDACS impact (Sendai) rows for three multi-place floods, copied VERBATIM
(fields trimmed to those the code reads) from the real GDACS geteventdata
responses downloaded on 4 Nov 2026 for the 12-month evaluation:

  INDONESIA_DEATHS  FL 1103633 (Indonesia, Nov-Dec 2025): 17 death rows from
                    12 places. The old "latest row per country" rule showed 1.
  THAILAND_AFFECTED FL 1103621 (Thailand, Nov 2025): a nationwide row plus
                    provincial ones (the province reports more than the nation).
  ODISHA_EVACUATED  FL 1104121 (India, Aug-Sep 2026): the same state in two
                    flood waves six weeks apart, plus two districts.
"""

INDONESIA_DEATHS = [
    {'country': 'Indonesia', 'dateinsert': '2025-11-29T07:42:04.087', 'description': 'Regency, Sibolga', 'expires_date': '2025-11-28T12:12:25', 'onset_date': '2025-11-28T12:12:25', 'region': 'Sibolga', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '60'},
    {'country': 'Indonesia', 'dateinsert': '2025-12-02T16:35:38.93', 'description': 'District, Majenang', 'expires_date': '2025-11-17T13:17:46', 'onset_date': '2025-11-17T13:17:46', 'region': 'Majenang', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '13'},
    {'country': 'Indonesia', 'dateinsert': '2025-12-16T08:15:16.017', 'description': '1 [people] Fatalities in Denpasar, Denpasar City, Bali, Indonesia', 'expires_date': '2025-12-14T01:00:00', 'onset_date': '2025-12-14T01:00:00', 'region': 'Denpasar', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '1'},
    {'country': 'Indonesia', 'dateinsert': '2025-12-31T08:55:01.71', 'description': '1 [people] Fatalities in Padarincang, Serang Regency, Banten, Indonesia', 'expires_date': '2025-12-30T01:00:00', 'onset_date': '2025-12-28T01:00:00', 'region': 'Indonesia', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '1'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.327', 'description': '3 [people] Fatalities in North Tapanuli Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-27T01:00:00', 'onset_date': '2025-11-25T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '3'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.34', 'description': '16 [people] Fatalities in Bener Meriah Regency, Aceh, Indonesia', 'expires_date': '2025-11-30T01:00:00', 'onset_date': '2025-11-24T01:00:00', 'region': 'Aceh', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '16'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.457', 'description': '11 [people] Fatalities in North Tapanuli Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-27T01:00:00', 'onset_date': '2025-11-25T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '11'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.477', 'description': '120 [people] Fatalities in Agam Regency, West Sumatra, Indonesia', 'expires_date': '2025-11-30T01:00:00', 'onset_date': '2025-11-29T01:00:00', 'region': 'Indonesia', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '120'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.52', 'description': '15 [people] Fatalities in South Tapanuli Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-28T01:00:00', 'onset_date': '2025-11-24T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '15'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.607', 'description': '5 [people] Fatalities in Humbang Hasundutan Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-28T01:00:00', 'onset_date': '2025-11-25T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '5'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.72', 'description': '6 [people] Fatalities in Humbang Hasundutan Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-30T01:00:00', 'onset_date': '2025-11-25T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '6'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.823', 'description': '51 [people] Fatalities in Central Tapanuli Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-28T01:00:00', 'onset_date': '2025-11-22T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '51'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.847', 'description': '4 [people] Fatalities in Tapteng, Pandan, Central Tapanuli Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-25T01:00:00', 'onset_date': '2025-11-22T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '4'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.867', 'description': '2 [people] Fatalities in West Pakpak, North Sumatra, Indonesia', 'expires_date': '2025-11-30T01:00:00', 'onset_date': '2025-11-29T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '2'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.903', 'description': '8 [people] Fatalities in South Tapanuli Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-26T01:00:00', 'onset_date': '2025-11-24T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '8'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:03.913', 'description': '46 [people] Fatalities in South Tapanuli Regency, North Sumatra, Indonesia', 'expires_date': '2025-11-28T01:00:00', 'onset_date': '2025-11-24T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '46'},
    {'country': 'Indonesia', 'dateinsert': '2026-01-05T19:27:04.16', 'description': '74 [people] Fatalities in Agam Regency, West Sumatra, Indonesia', 'expires_date': '2025-11-30T01:00:00', 'onset_date': '2025-11-29T01:00:00', 'region': 'Sumatra', 'sendainame': 'death', 'sendaitype': 'A', 'sendaivalue': '74'},
]

THAILAND_AFFECTED = [
    {'country': 'Thailand', 'dateinsert': '2025-11-22T09:26:48.497', 'description': 'Country, Thailand', 'expires_date': '2025-11-21T13:35:05', 'onset_date': '2025-11-21T13:35:05', 'region': 'Thailand', 'sendainame': 'affected', 'sendaitype': 'B', 'sendaivalue': '456000'},
    {'country': 'Thailand', 'dateinsert': '2025-12-03T01:30:27.677', 'description': '5,000 [people] Affected in Ratsada District, Trang Province, Thailand', 'expires_date': '2025-11-25T01:00:00', 'onset_date': '2025-11-21T01:00:00', 'region': 'Thailand', 'sendainame': 'affected', 'sendaitype': 'B', 'sendaivalue': '5000'},
    {'country': 'Thailand', 'dateinsert': '2025-12-03T01:30:27.69', 'description': '697,231 [people] Affected in Songkhla Province, Thailand', 'expires_date': '2025-11-25T01:00:00', 'onset_date': '2025-11-19T01:00:00', 'region': 'Songkhla Province', 'sendainame': 'affected', 'sendaitype': 'B', 'sendaivalue': '697231'},
]

ODISHA_EVACUATED = [
    {'country': 'India', 'dateinsert': '2026-08-27T10:18:01.457', 'description': '3,000 [people] Evacuated in Balasore District, Odisha, India', 'expires_date': '2026-08-14T01:00:00', 'onset_date': '2026-08-13T01:00:00', 'region': 'Balasore District', 'sendainame': 'displaced', 'sendaitype': 'B', 'sendaivalue': '3000'},
    {'country': 'India', 'dateinsert': '2026-08-27T10:18:01.517', 'description': '237,000 [people] Evacuated in Odisha, India', 'expires_date': '2026-08-16T02:00:00', 'onset_date': '2026-08-13T02:00:00', 'region': 'Odisha', 'sendainame': 'displaced', 'sendaitype': 'B', 'sendaivalue': '237000'},
    {'country': 'India', 'dateinsert': '2026-08-27T10:26:30.06', 'description': '70 [people] Evacuated in Nabarangpur District, Odisha, India', 'expires_date': '2026-08-24T01:00:00', 'onset_date': '2026-08-24T01:00:00', 'region': 'Nabarangpur District', 'sendainame': 'displaced', 'sendaitype': 'B', 'sendaivalue': '70'},
    {'country': 'India', 'dateinsert': '2026-09-28T12:53:46.53', 'description': '8,082 [people] Evacuated in Odisha, India', 'expires_date': '2026-09-25T01:00:00', 'onset_date': '2026-09-23T01:00:00', 'region': 'Odisha', 'sendainame': 'displaced', 'sendaitype': 'B', 'sendaivalue': '8082'},
    {'country': 'India', 'dateinsert': '2026-09-28T12:53:46.54', 'description': '70,000 [people] Evacuated in Odisha, India', 'expires_date': '2026-09-27T02:00:00', 'onset_date': '2026-09-23T02:00:00', 'region': 'Odisha', 'sendainame': 'displaced', 'sendaitype': 'B', 'sendaivalue': '70000'},
    {'country': 'India', 'dateinsert': '2026-09-28T12:53:46.593', 'description': '15,000 [people] Evacuated in Odisha, India', 'expires_date': '2026-09-26T02:00:00', 'onset_date': '2026-09-23T02:00:00', 'region': 'Odisha', 'sendainame': 'displaced', 'sendaitype': 'B', 'sendaivalue': '15000'},
    {'country': 'India', 'dateinsert': '2026-09-28T12:53:46.627', 'description': '100,000 [people] Evacuated in Odisha, India', 'expires_date': '2026-09-27T02:00:00', 'onset_date': '2026-09-23T02:00:00', 'region': 'Odisha', 'sendainame': 'displaced', 'sendaitype': 'B', 'sendaivalue': '100000'},
]

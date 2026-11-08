"""
Two real earthquakes 18 minutes apart in Qinghai, China, 28 Jul 2026, as
published by GDACS (search list) and USGS (FDSN), fields trimmed, values
verbatim. Downloaded 4 Nov 2026 for the 12-month evaluation.

  M5.7 03:16 UTC  GDACS EQ 1554510  =  USGS us6000tga6  (GDACS names it as source)
  M5.8 03:34 UTC  GDACS EQ 1554511  =  USGS us6000tga9

The M5.8 GDACS record lies 2.4 km from the M5.7's USGS epicentre, nearer than
the M5.7's own GDACS record (5.0 km), so distance-first matching swapped
them; time-first matching does not.
"""

GDACS = [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [99.5513, 35.3866]}, 'properties': {'eventtype': 'EQ', 'eventid': 1554511, 'episodeid': 1721183, 'alertlevel': 'Green', 'alertscore': 1, 'iscurrent': 'false', 'country': 'China', 'fromdate': '2026-07-28T03:34:05', 'todate': '2026-07-28T03:34:05', 'severitydata': {'severity': 5.8, 'severitytext': 'Magnitude 5.8M, Depth:10km', 'severityunit': 'M'}, 'affectedcountries': [{'iso2': 'CN', 'iso3': 'CHN', 'countryname': 'China'}]}}, {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [99.5198, 35.3685]}, 'properties': {'eventtype': 'EQ', 'eventid': 1554510, 'episodeid': 1721184, 'alertlevel': 'Orange', 'alertscore': 2, 'iscurrent': 'false', 'country': 'China', 'fromdate': '2026-07-28T03:16:08', 'todate': '2026-07-28T03:16:08', 'severitydata': {'severity': 5.7, 'severitytext': 'Magnitude 5.7M, Depth:10km', 'severityunit': 'M'}, 'affectedcountries': [{'iso2': 'CN', 'iso3': 'CHN', 'countryname': 'China'}]}}]

USGS = [{'type': 'Feature', 'id': 'us6000tga9', 'geometry': {'type': 'Point', 'coordinates': [99.5723, 35.4257, 10]}, 'properties': {'mag': 5.8, 'time': 1785209645633, 'type': 'earthquake', 'status': 'reviewed', 'place': '193 km NW of Oula Xiuma, China', 'magType': 'mww', 'ids': ',us6000tga9,usauto6000tga9,', 'alert': 'yellow', 'updated': 1791931337040}}, {'type': 'Feature', 'id': 'us6000tga6', 'geometry': {'type': 'Point', 'coordinates': [99.5465, 35.4075, 10]}, 'properties': {'mag': 5.7, 'time': 1785208568805, 'type': 'earthquake', 'status': 'reviewed', 'place': '193 km NW of Oula Xiuma, China', 'magType': 'mww', 'ids': ',us6000tga6,usauto6000tga6,', 'alert': 'yellow', 'updated': 1791931339040}}]

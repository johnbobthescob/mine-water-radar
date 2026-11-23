"""The complete public MINEDEX project spine; operator is not supplied."""
from urllib.parse import urlencode

from .arcgis import ArcGISClient


def citation(record):
    # Construct from identity rather than trusting arbitrary source HTML links.
    return "https://minedex.dmirs.wa.gov.au/Web/common/jump.jsp?" + urlencode({"jumpType": "SITE", "id": record["site_code"]})


def fetch(http):
    return ArcGISClient(http, "minedex").fetch({"where": "1=1"})

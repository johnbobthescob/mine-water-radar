"""WA Mining referrals; status wording and year values are preserved verbatim."""
from urllib.parse import urlencode

from .arcgis import ArcGISClient
from .http import FetchError
from .registry import EPBC_LAYER, EPBC_WHERE


def citation(record):
    reference = str(record["REFERENCE_NUMBER"]).replace("'", "''")
    return EPBC_LAYER + "/query?" + urlencode({"f": "json", "where": f"REFERENCE_NUMBER='{reference}'",
                                               "outFields": "REFERENCE_NUMBER", "returnGeometry": "false"})


def fetch(http):
    def recheck(record):
        if record["PRIMARY_JURISDICTION"] != "WA" or record["CATEGORY"] != "Mining":
            raise FetchError("EPBC response contains records outside WA Mining scope")
        return True
    return ArcGISClient(http, "epbc").fetch(
        {"where": EPBC_WHERE}, recheck=recheck)

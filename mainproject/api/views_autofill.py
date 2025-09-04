import os
import re
import requests
from typing import Dict, Any, List, Optional

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticatedOrReadOnly

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_CX  = os.getenv("GOOGLE_CSE_CX", "")

import logging
logger = logging.getLogger(__name__)
# ---------- helpers ----------

def _clean(s: Optional[str]) -> str:
    return (s or "").strip()

def _guess_brand_model(name: str) -> Dict[str, str]:
    """
    Heuristic: brand = first token; model = first long alnum/hyphen token.
    e.g. 'Cummins 125 kVA DG Set KTA50-GS8' -> brand Cummins, model KTA50-GS8
    """
    name = _clean(name)
    brand = name.split()[0] if name else ""
    m = re.search(r"\b([A-Z0-9][A-Z0-9\-]{2,})\b", name.upper())
    model = m.group(1) if m else ""
    return {"brand": brand, "model": model}

def _normalize_unit(unit_raw: str) -> str:
    u = (unit_raw or "").lower()
    if "kva" in u: return "kVA"
    if re.search(r"\bkw\b", u): return "kW"
    if re.search(r"\btr\b", u) or "ton of refrigeration" in u: return "TR"
    if re.search(r"\bcfm\b", u): return "CFM"
    if re.search(r"\blpm\b", u) or "l/min" in u: return "LPM"
    if re.search(r"\bhp\b", u): return "HP"
    if re.fullmatch(r"ton(ne|s)?", u): return "TON"
    return unit_raw.upper()

def _extract_capacity(text: str) -> Optional[Dict[str, str]]:
    """
    Finds patterns like '125 kVA', '20 TR', '300 CFM', '45 kW', '3000 LPM', '5 HP', '10 ton'.
    Returns {'value': '125', 'unit': 'kVA'} or None.
    """
    if not text: return None
    s = text.lower()
    m = re.search(
        r"(\d{1,5}(?:[.,]\d{1,2})?)\s*(kva|kw|tr|cfm|lpm|hp|ton|tons|tonne|tonnes)\b",
        s, flags=re.IGNORECASE
    )
    if not m: return None
    value = m[1].replace(",", ".")
    unit = _normalize_unit(m[2])
    return {"value": value, "unit": unit}

def _extract_cost(text: str) -> Optional[Dict[str, str]]:
    """
    Pulls INR or USD-like amounts from snippets/titles if present.
    Returns {'amount': '123456', 'currency': 'INR'} or None.
    """
    if not text: return None
    t = text.replace("\u00a0", " ")

    m_inr = re.search(r"(₹|INR|Rs\.?)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", t, flags=re.I)
    if m_inr:
        return {"amount": m_inr[2].replace(",", ""), "currency": "INR"}

    m_usd = re.search(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)", t)
    if m_usd:
        return {"amount": m_usd[1].replace(",", ""), "currency": "USD"}

    # generic large number if preceded by 'price'/'cost'
    m_hint = re.search(r"(price|cost)\D{0,8}([0-9][0-9,]{3,})", t, flags=re.I)
    if m_hint:
        return {"amount": m_hint[2].replace(",", ""), "currency": ""}

    return None

def _google_kg(query: str) -> List[Dict[str, Any]]:
    if not GOOGLE_API_KEY:
        return []
    try:
        url = "https://kgsearch.googleapis.com/v1/entities:search"
        params = {"query": query, "key": GOOGLE_API_KEY, "limit": 5, "types": "Product"}
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning("KG unreachable: %s", e)
        return []

    out = []
    for item in r.json().get("itemListElement", []):
        res = item.get("result", {}) or {}
        name = res.get("name", "")
        url1 = (res.get("detailedDescription") or {}).get("url") or res.get("url")
        desc = res.get("description") or (res.get("detailedDescription") or {}).get("articleBody", "")
        bm = _guess_brand_model(name)
        blob = " ".join([name or "", desc or ""])
        cap = _extract_capacity(blob)
        cost = _extract_cost(blob)
        out.append({
            "brand": bm["brand"],
            "model": bm["model"],
            "capacity_value": cap["value"] if cap else "",
            "capacity_unit": cap["unit"] if cap else "",
            "purchase_cost": cost["amount"] if cost else "",
            "currency": cost["currency"] if cost else "",
            "url": url1 or "",
            "_score": float(item.get("resultScore") or 0.0),
        })
    return out



def _google_cse(query: str) -> List[Dict[str, Any]]:
    if not (GOOGLE_API_KEY and GOOGLE_CSE_CX):
        return []
    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {"key": GOOGLE_API_KEY, "cx": GOOGLE_CSE_CX,
                  "q": f'{query} datasheet OR "spec sheet" OR specifications OR price'}
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning("CSE unreachable: %s", e)
        return []

    out = []
    for it in (r.json().get("items") or [])[:5]:
        title = it.get("title") or ""
        snippet = it.get("snippet") or ""
        link = it.get("link") or ""
        bm = _guess_brand_model(title)
        blob = " ".join([title, snippet])
        cap = _extract_capacity(blob)
        cost = _extract_cost(blob)
        out.append({
            "brand": bm["brand"],
            "model": bm["model"],
            "capacity_value": cap["value"] if cap else "",
            "capacity_unit": cap["unit"] if cap else "",
            "purchase_cost": cost["amount"] if cost else "",
            "currency": cost["currency"] if cost else "",
            "url": link,
            "_score": 0.55,
        })
    return out


def _dedupe_keep_best(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Dedupe by (brand, model); keep the one with highest _score or with capacity/cost present.
    """
    by_key: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r.get('brand','').lower()}|{r.get('model','').lower()}"
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = r
        else:
            # prefer one that has capacity/cost; else higher score
            def weight(x: Dict[str, Any]) -> float:
                w = x.get("_score", 0.0)
                if x.get("capacity_value"): w += 1.0
                if x.get("purchase_cost"): w += 1.0
                return w
            if weight(r) > weight(prev):
                by_key[key] = r
    # strip internal field
    cleaned = []
    for v in by_key.values():
        v.pop("_score", None)
        cleaned.append(v)
    return cleaned

# ---------- API view ----------

USE_KG = os.getenv("USE_KG", "1") == "1"

class AssetAutofillView(APIView):
    """
    GET /api/assets/autofill/?q=<asset name>

    Response:
    {
      "query": "...",
      "candidates": [
        {
          "brand": "Cummins",
          "model": "KTA50-GS8",
          "capacity_value": "125",
          "capacity_unit": "kVA",
          "purchase_cost": "1200000",
          "currency": "INR",
          "url": "https://..."
        },
        ...
      ]
    }
    """
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, *args, **kwargs):
        q = _clean(request.GET.get("q"))
        if not q:
            return Response({"detail": "Missing query (?q=...)"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            rows = []
            if USE_KG:
                rows += _google_kg(q)
            rows += _google_cse(q)

            candidates = _dedupe_keep_best(rows)
            return Response({"query": q, "candidates": candidates[:8]})
        except requests.HTTPError as e:
            return Response({"detail": f"Upstream error: {e}"},
                            status=status.HTTP_502_BAD_GATEWAY)
        except Exception as e:
            return Response({"detail": f"Server error: {e}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

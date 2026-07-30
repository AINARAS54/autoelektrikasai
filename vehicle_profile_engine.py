import json
from pathlib import Path
from vehicle_engine import vehicle_label, brand_slug

DEFAULTS = {
    "ICE": {"platform":"ICE","has_starter":True,"has_alternator":True,"has_spark_plugs":None,"has_injectors":True,"has_hv_battery":False,"has_12v_battery":True,"has_dcdc":False},
    "EV": {"platform":"EV","has_starter":False,"has_alternator":False,"has_spark_plugs":False,"has_injectors":False,"has_hv_battery":True,"has_12v_battery":True,"has_dcdc":True},
    "HYBRID": {"platform":"HYBRID","has_starter":None,"has_alternator":None,"has_spark_plugs":True,"has_injectors":True,"has_hv_battery":True,"has_12v_battery":True,"has_dcdc":True},
}

def _norm(v): return (v or "").strip().lower()
def _model_slug(v): return _norm(v).replace(".","").replace("-","_").replace(" ","_")

def infer_platform(vehicle: dict) -> str:
    brand, model = _norm(vehicle.get("brand")), _norm(vehicle.get("model"))
    if brand == "tesla" or model in {"i3","i4","i5","i7","ix","leaf","id.3","id.4","model 3","model y"}:
        return "EV"
    if any(x in model for x in ["hybrid","phev","plug-in"]):
        return "HYBRID"
    return "ICE"

def _load(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def get_vehicle_profile(base_dir: Path, ctx: dict) -> dict:
    vehicle = ctx.get("vehicle") if isinstance(ctx.get("vehicle"), dict) else {}
    platform = infer_platform(vehicle)
    root = Path(base_dir) / "vehicle_profiles"
    candidates = []
    brand = brand_slug(vehicle)
    model = _model_slug(vehicle.get("model",""))
    if brand and model:
        candidates.append(root / brand / f"{model}.json")
    candidates.append(root / "generic" / f"{platform.lower()}.json")
    profile = None
    for p in candidates:
        if p.exists():
            profile = _load(p)
            if profile:
                profile["_source_file"] = str(p)
                break
    profile = profile or dict(DEFAULTS[platform])
    profile["platform"] = profile.get("platform") or platform
    profile["vehicle"] = vehicle
    profile["vehicle_label"] = vehicle_label(vehicle)
    return profile

def incompatible_reason(profile: dict, text: str):
    t = _norm(text)
    if profile.get("platform") != "EV":
        return None
    if any(x in t for x in ["starter","starteris","starterio"]):
        return "Šis automobilis yra elektromobilis ir neturi įprasto starterio."
    if any(x in t for x in ["generator","alternator"]):
        return "Šis automobilis neturi generatoriaus. 12 V sistemą krauna DC/DC keitiklis."
    if any(x in t for x in ["žvak","zvak","ritė","rite","kibirkšt","kibirkst"]):
        return "Šis automobilis neturi uždegimo žvakių, uždegimo ričių ar kibirkšties sistemos."
    if any(x in t for x in ["purkštuk","purkstuk"]):
        return "Šis automobilis neturi degalų purkštukų."
    return None

def profile_summary(profile: dict) -> dict:
    return {k: profile.get(k) for k in ["vehicle_label","platform","has_starter","has_alternator","has_spark_plugs","has_injectors","has_hv_battery","has_12v_battery","has_dcdc"]}

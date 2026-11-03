"""Field dictionary for the ShCB physics files (docs/14-physics-fields.md).

**Key hash [proven]:** a key is Bob Jenkins' *lookup2* hash (``initval`` 0) of the property name in
upper case. The file stores the 32-bit hash little-endian, so ``key_hex`` (the four file bytes) is
``lookup2(name.upper()).to_bytes(4, "little").hex()``. For example ``RPMTorque`` -> ``8b0ab771`` and
``BrakeTorque`` -> ``4ba4817a``. The names are rFactor-style HDV / ENG / TBC property names: object keys
are the section headers (``[GENERAL]``, ``[FRONTWING]``, ``[FRONTLEFT]``...). AMS2 renamed most of the
properties, so only about 200 of the ~1000 keys could be named by their hash. The rest are named here
by analogy with rFactor plus their values and in-game tests.

Public API::

    key_for_name("BrakeTorque") -> "4ba4817a"
    FIELDS[kind][key_hex] -> {"name", "unit", "desc", "confidence", "editable", "name_source"}
    describe(kind, key_hex) -> entry dict (falls back to the survey of base files for unknown keys)
    list_fields(kind, data) -> [ {"index", "path", "key", "name", "type", "value", "confidence", ...} ]
    kind_of_path("x/engines/a.edfbin") -> "engine"

``kind`` is one of ``KINDS``. ``confidence`` describes the *meaning*:
- ``proven``: verified in game or by an exact, unambiguous value match;
- ``strong``: rFactor convention plus consistent values across the base cars;
- ``guess``;
- ``unknown``: not identified, described only by the base-car survey.

``name_source`` is ``"hash"`` when the name itself is verified by the key hash. Otherwise it is
``"analogy"`` (an rFactor name we could not verify) or ``"descriptive"`` (our own label).

Setup values use the rFactor pattern ``XRange = (start, step, count)`` followed by a separate
``XSetting`` (u8 index). The effective value is ``start + step * setting``; ``count == 0`` means the
value is fixed and not adjustable.
"""
from __future__ import annotations

import struct

from . import shcb
from .fields_survey import SURVEY, HASH_NAMES

KINDS = ("engine", "chassis", "gearbox", "suspension", "clutch", "failures", "turbo", "boost", "tyres")
EXT_KIND = {".edfbin": "engine", ".cdfbin": "chassis", ".gdfbin": "gearbox", ".sdfbin": "suspension",
            ".cmfbin": "clutch", ".fmfbin": "failures", ".tbfbin": "turbo", ".bbfbin": "boost",
            ".hdtbin": "tyres"}

# ----------------------------------------------------------------------------- key hash

_M = 0xFFFFFFFF


def _mix(a, b, c):
    a = (a - b - c) & _M; a ^= c >> 13
    b = (b - c - a) & _M; b ^= (a << 8) & _M
    c = (c - a - b) & _M; c ^= b >> 13
    a = (a - b - c) & _M; a ^= c >> 12
    b = (b - c - a) & _M; b ^= (a << 16) & _M
    c = (c - a - b) & _M; c ^= b >> 5
    a = (a - b - c) & _M; a ^= c >> 3
    b = (b - c - a) & _M; b ^= (a << 10) & _M
    c = (c - a - b) & _M; c ^= b >> 15
    return a, b, c


def lookup2(k: bytes, initval: int = 0) -> int:
    """Bob Jenkins' lookup2 ``hash()`` (1996), little-endian word reads."""
    a = b = 0x9E3779B9
    c = initval
    n, i = len(k), 0
    while n >= 12:
        a = (a + struct.unpack_from("<I", k, i)[0]) & _M
        b = (b + struct.unpack_from("<I", k, i + 4)[0]) & _M
        c = (c + struct.unpack_from("<I", k, i + 8)[0]) & _M
        a, b, c = _mix(a, b, c)
        i += 12
        n -= 12
    c = (c + len(k)) & _M
    t = k[i:] + b"\0" * 12
    a = (a + struct.unpack_from("<I", t, 0)[0]) & _M
    b = (b + struct.unpack_from("<I", t, 4)[0]) & _M
    c = (c + (struct.unpack_from("<I", t, 8)[0] << 8)) & _M
    return _mix(a, b, c)[2]


def key_for_name(name: str) -> str:
    """The 4 file bytes (hex) of a property / section name, e.g. ``key_for_name("Mass") == "670b57ab"``."""
    return lookup2(name.upper().encode("latin-1")).to_bytes(4, "little").hex()


# ----------------------------------------------------------------------------- dictionary
# key: (name, unit, desc, confidence, editable).  "name_source" is derived: "hash" when the key hash
# of the name matches, else "analogy" for rF-style names and "descriptive" for snake_case labels.

_E = {  # engine .edfbin
    "8b0ab771": ("RPMTorque", "rpm, Nm, Nm", "Torque table row (rpm, engine-braking torque at closed throttle (<= 0), full-throttle torque). Repeated, any row count. Interpolated; the torque is scaled by the chassis/engine torque and power multipliers (a3bf1e60/c3667d2e) and the braking column by 27844d75.", "proven", True),
    "4ae2dd6c": ("FuelConsumption", "?", "Fuel use coefficient (Veneno 8e-5, Lancer 1.7e-5). rF FuelConsumption.", "guess", True),
    "d2a29232": ("FuelEstimate", "factor", "1.0 on most engines, 0.85 on the Lancer R. rF FuelEstimate (fuel-use estimate multiplier). Not the torque multiplier.", "guess", False),
    "4665ae87": ("EngineInertia", "kg m^2", "Rotating inertia of the engine (Veneno 0.28, Camaro 0.2, Lancer 0.135, F1 0.05). Plausible magnitudes for crank + flywheel.", "strong", True),
    "fc513488": ("engine_inertia_2", "kg m^2", "Second inertia, usually equal to 4665ae87 or slightly lower (Veneno 0.2).", "guess", True),
    "40f1d2b9": ("IdleThrottle", "fraction", "Idle throttle opening (0.01-0.04).", "strong", True),
    "4d239754": ("IdleRPMLogic", "rpm, rpm", "Idle controller window (low, high), e.g. Veneno (850, 950), F1 (3750, 3750).", "strong", True),
    "219899ae": ("LaunchEfficiency", "", "Launch control efficiency (null = 0 / default).", "guess", False),
    "7902b6bd": ("LaunchRPMLogic", "rpm, rpm", "Launch-control rpm window (Camaro 3000/4500, Veneno 4000/5000, F1 11500). Scale it with the rev limit.", "strong", True),
    "dea72eb7": ("RevLimitRange", "rpm, rpm step, count", "Rev limit setup range. Element 0 is the rev limit (Veneno 8500).", "proven", True),
    "a55cc1c4": ("RevLimitSetting", "index", "Rev-limit setting index.", "strong", True),
    "19668af9": ("RevLimitLogic", "rpm", "Limiter hysteresis band (50; Lancer 15).", "strong", True),
    "d5b3f787": ("engine_flag_d5b3", "bool", "Flag (1). Also appears in the chassis [ENGINE] section.", "unknown", False),
    "83152f20": ("EngineBoostRange", "start, step, count", "Engine map / boost-mixture setup range (0, 1, 0).", "guess", False),
    "c44473f5": ("EngineBoostSetting", "index", "Engine map setting.", "guess", False),
    "bf847cf1": ("BoostEffects", "", "(0, 0.0001, 10) on some cars: effect of the engine map on fuel/wear.", "guess", False),
    "be71ed67": ("engine_be71", "", "Small int (2).", "unknown", False),
    "afd78add": ("OptimumOilTemp", "degC", "Optimum oil temperature (95-110).", "strong", False),
    "54106db1": ("CombustionHeat", "", "Heat from combustion (40-50).", "strong", False),
    "f6e39fd9": ("EngineSpeedHeat", "", "Heat from engine speed (~0.0012-0.0018).", "strong", False),
    "b30f25fc": ("OilMinimumCooling", "", "Oil cooling at zero speed.", "strong", False),
    "a700d23a": ("OilWaterHeatTransfer", "", "Oil <-> water heat transfer (base, speed).", "strong", False),
    "67171586": ("WaterMinimumCooling", "", "Water cooling at zero speed.", "strong", False),
    "6ada2b3a": ("RadiatorCooling", "", "Radiator cooling (base, per speed).", "strong", False),
    "3f6b7be7": ("OilWarningTemp", "degC", "130 on nearly every car. One of OilWarningTemp / WaterWarningTemp.", "guess", False),
    "6d47c1b2": ("WaterWarningTemp", "degC", "115 on nearly every car.", "guess", False),
    "d39464af": ("rev_limiter_cut", "rpm, rpm", "Limiter cut point and width just under the rev limit (Veneno 8100/100, Camaro 5800/165). Scale it with the rev limit, or power is cut early.", "strong", True),
    "0acea858": ("LifetimeOilTemp", "degC, degC", "Engine life vs oil temperature (avg, var), e.g. (106, 3).", "strong", False),
    "0571c719": ("LifetimeEngineRPM", "", "Engine life vs rpm (64 engines, e.g. Lancer (1e5, 75000)).", "guess", False),
    "f75f822b": ("LifetimeAvg", "s", "Average engine life.", "strong", False),
    "527b76cd": ("LifetimeVar", "s", "Engine life variation.", "strong", False),
    "c1f4543c": ("EngineEmission", "m", "Exhaust emitter position (x, y, z).", "strong", False),
    "ceb17525": ("EngineSound", "m", "Engine sound source position (x, y, z).", "strong", False),
    "118ba381": ("SpeedLimiter", "bool", "Pit speed limiter fitted (1). Order guess against OnboardStarter.", "guess", False),
    "12fab3eb": ("OnboardStarter", "bool", "1 on all cars; also in the chassis [ENGINE] section.", "guess", False),
    "af00b3ba": ("Layout", "string offset", "Engine layout string (V8, V12, S4, F6...; decrypt with ev.strings_of).", "proven", False),
    "5217fb41": ("StarterTiming", "s", "Starter timing (crank, catch, ?).", "guess", False),
    "92c7cd7c": ("EngineSize", "litres", "Displacement. No measurable effect on driving.", "proven", True),
    "2c1e7ee9": ("engine_flag_2c1e", "u8", "Flag (1).", "unknown", False),
    "ba65dd60": ("BoostTorque", "", "Turbo engines: boost -> torque coefficient (7e-6).", "strong", False),
    "819217e0": ("engine_819217e0", "int", "Turbo engines: 200-550 (boost pressure cap / wastegate?).", "guess", False),
    "515f5e83": ("RPMBoost", "rpm, mult x5", "Turbo engines: torque multiplier per boost level vs rpm. Multiplies the torque table. EVs must flatten it to 1.0 (doc 11).", "proven", True),
    "04454929": ("throttle_map", "throttle %, rpm %, ?, out", "Throttle map rows (21 x 21: throttle % x rpm %) giving the effective throttle.", "strong", True),
    "32ac83bd": ("FuelDensity", "", "Fuel density.", "strong", False),
    "63233a14": ("engine_63233a14", "", "(0, 0, 0) on most engines.", "unknown", False),
    "d774451a": ("engine_d774451a", "start, step, count", "(0, 0.01, 0/100): a setup range (e.g. engine braking map).", "guess", False),
    "ca2fd134": ("engine_ca2fd134", "index", "Setting index for d774451a.", "guess", False),
    "df8664fc": ("engine_df8664fc", "", "Null on all engines.", "unknown", False),
    "be7f531a": ("engine_be7f531a", "", "43 engines, 87-90.", "unknown", False),
    "a3bf1e60": ("torque_mult", "factor", "Engine-file copy of the chassis [ENGINE] torque multiplier; multiplied with the chassis value.", "proven", True),
    "c3667d2e": ("power_mult", "factor", "Engine-file copy of the power multiplier; multiplied with the chassis value.", "proven", True),
    "27844d75": ("engine_brake_mult", "factor", "Engine-file copy of the engine-braking multiplier; multiplied with the chassis value.", "proven", True),
}

_CORNER = {  # chassis [FRONTLEFT]/[FRONTRIGHT]/[REARLEFT]/[REARRIGHT]
    "b3d821f7": ("BumpTravel", "m", "Suspension bump travel to the bump stop (<= 0 in AMS2).", "strong", True),
    "177b8a89": ("ReboundTravel", "m", "Rebound travel (negative).", "strong", True),
    "7fc6f841": ("BumpStopSpring", "N/m", "Bump stop spring rate.", "strong", True),
    "cb91f163": ("BumpStopRisingSpring", "N/m^2", "Bump stop rising (progressive) rate.", "strong", True),
    "71746eeb": ("BumpStopDamper", "N/(m/s)", "Bump stop damping.", "strong", True),
    "ddd6e175": ("BumpStopRisingDamper", "", "Bump stop rising damping.", "guess", True),
    "70026d2b": ("BumpStage2", "m/s", "Bump damper knee speed (slow -> fast).", "strong", True),
    "1f7d2d8e": ("ReboundStage2", "m/s", "Rebound damper knee speed.", "strong", True),
    "7f0e4ca5": ("corner_7f0e4ca5", "u8", "1 at the front, 2 at the rear (axle id?).", "guess", False),
    "57510f51": ("SpinInertia", "kg m^2", "Wheel + tyre spin inertia.", "strong", True),
    "2599cd41": ("spin_inertia_2", "kg m^2", "Equal to SpinInertia in every car (driven / undriven copy?).", "guess", True),
    "beb9bbab": ("PushrodSpindle", "m", "Spring/damper attachment on the upright (x, y, z).", "strong", True),
    "1911eace": ("PushrodBody", "m", "Spring/damper attachment on the body.", "strong", True),
    "24e19cb2": ("CamberRange", "deg", "Static camber setup range; c172f309 = CamberSetting.", "strong", True),
    "c172f309": ("CamberSetting", "index", "Camber setting.", "strong", True),
    "a6dac6bf": ("PressureRange", "kPa", "Tyre pressure setup range (e.g. 145, 1, 60); bb9616f6 = PressureSetting.", "strong", True),
    "bb9616f6": ("PressureSetting", "index", "Tyre pressure setting: pressure = start + setting kPa.", "strong", True),
    "bb592cd5": ("PackerRange", "m", "Packer setup range; d87d1714 = PackerSetting.", "strong", True),
    "d87d1714": ("PackerSetting", "index", "Packer setting.", "strong", True),
    "44495d88": ("SpringMult", "factor", "Wheel-rate multiplier (motion ratio) for the spring.", "strong", True),
    "a5123d0d": ("SpringRange", "N/m", "Spring rate setup range; ceaa7a97 = SpringSetting.", "proven", True),
    "ceaa7a97": ("SpringSetting", "index", "Spring setting.", "strong", True),
    "d7c60d7a": ("RideHeightRange", "m", "Ride height setup range; 6d049405 = RideHeightSetting.", "strong", True),
    "6d049405": ("RideHeightSetting", "index", "Ride height setting.", "strong", True),
    "51374153": ("DamperMult", "factor", "Damper motion-ratio multiplier.", "strong", True),
    "0c43d9d0": ("SlowBumpRange", "N/(m/s)", "Slow bump damping range; d19e2c0a = setting.", "strong", True),
    "d19e2c0a": ("SlowBumpSetting", "index", "", "strong", True),
    "3089ec3d": ("FastBumpRange", "N/(m/s)", "Fast bump damping range; 38382587 = setting.", "strong", True),
    "38382587": ("FastBumpSetting", "index", "", "strong", True),
    "bcc0a291": ("SlowReboundRange", "N/(m/s)", "Slow rebound damping range; 2273d781 = setting.", "strong", True),
    "2273d781": ("SlowReboundSetting", "index", "", "strong", True),
    "bc6d0ef7": ("FastReboundRange", "N/(m/s)", "Fast rebound damping range; b8b0022e = setting.", "strong", True),
    "b8b0022e": ("FastReboundSetting", "index", "", "strong", True),
    "097ad24b": ("BrakeDiscRange", "m", "Brake disc thickness range; 957dfb9d = setting.", "strong", False),
    "957dfb9d": ("BrakeDiscSetting", "index", "", "strong", False),
    "ed3fc221": ("BrakePadRange", "index", "Brake pad compound range (0, 1, 5); 64d7a9e6 = setting.", "strong", False),
    "64d7a9e6": ("BrakePadSetting", "index", "", "strong", False),
    "b9cf18d1": ("brake_b9cf18d1", "", "0.001.", "unknown", False),
    "92aa0624": ("brake_optimum_temp", "degC, degC", "Brake optimum temperature window (Veneno 500-950, Lancer 400-650).", "guess", False),
    "023f01f1": ("brake_023f01f1", "", "0.2-0.75: brake torque at cold / fade?", "guess", False),
    "45813693": ("brake_45813693", "", "0.9.", "unknown", False),
    "e795a8d0": ("brake_temp_e795", "degC", "400-600: brake temperature point (glow / response curve).", "guess", False),
    "d0031855": ("brake_fade_temp", "degC", "850-1200: brake fade temperature.", "guess", False),
    "1ee5b64c": ("BrakeWearRate", "", "Brake wear rate (2e-11..6e-11).", "strong", False),
    "bd59c842": ("BrakeFailure", "", "Brake failure (avg, var).", "strong", False),
    "4ba4817a": ("BrakeTorque", "Nm", "Maximum brake torque of this wheel at 100 % pedal (Veneno 4800 F / 4200 R, Lancer 3800 / 3600, F1 6500). Scaled by brake pressure (CONTROLS d0003859) and the bias (a6321357). The main brake-force knob.", "strong", True),
    "6ea60dfb": ("BrakeHeating", "", "Brake heating per energy.", "strong", False),
    "1cd55c78": ("BrakeCooling", "", "Brake cooling (base, per speed).", "strong", False),
    "a26726e9": ("BrakeDuctCooling", "", "Extra cooling per brake-duct step.", "guess", False),
    "6c82e402": ("brake_disc_mass", "kg?", "1.8-3.8: disc thermal mass?", "guess", False),
    "ee67fd55": ("brake_disc_radius", "m?", "0.3-0.35.", "guess", False),
    "5d9e9a9f": ("brake_5d9e9a9f", "", "(0.0013, 4e-5): brake glow / wear vs temperature.", "unknown", False),
    "cea0756b": ("brake_cea0756b", "", "~2e-6.", "unknown", False),
    "c92a02bb": ("CGOffsetX", "m", "Lateral offset of the wheel CG.", "strong", False),
}

_C = {  # chassis .cdfbin
    # sections (object keys)
    "d1cc9bf2": ("[GENERAL]", "", "Section: mass, inertia, CG, fuel tank, undertray, AI and FFB parameters.", "proven", False),
    "e41224ba": ("[FRONTWING]", "", "Section: front wing aero.", "proven", False),
    "e1833aa6": ("[REARWING]", "", "Section: rear wing aero.", "proven", False),
    "c941a81c": ("[DIFFUSER]", "", "Section: diffuser / underbody aero (403 of 505 files).", "proven", False),
    "2bda9542": ("[BODYAERO]", "", "Section: body drag and lift.", "proven", False),
    "c815e223": ("suspension_section", "", "Section after [BODYAERO]: anti-roll bars, toe, caster, third springs (rF [SUSPENSION]; the name doesn't hash to that).", "strong", False),
    "080a14c5": ("[CONTROLS]", "", "Section: steering, brake bias/pressure, TC, ABS.", "proven", False),
    "3f9e4598": ("[ENGINE]", "", "Section: engine multipliers.", "proven", False),
    "9ef76784": ("[DRIVELINE]", "", "Section: clutch, shifting, wheel drive, differentials.", "proven", False),
    "12bc367d": ("[DAMAGE]", "", "Section: damage.", "proven", False),
    "7d16e29f": ("[FRONTLEFT]", "", "Section: front-left corner (springs, dampers, brakes).", "proven", False),
    "d6537908": ("front_right_section", "", "Section: front-right corner (same keys as [FRONTLEFT]).", "strong", False),
    "bf9f5ba2": ("[REARLEFT]", "", "Section: rear-left corner.", "proven", False),
    "cff2c932": ("[REARRIGHT]", "", "Section: rear-right corner.", "proven", False),
    "3dd3da1b": ("[REARWING2]", "", "Section: second rear wing (46 files).", "proven", False),
    # [GENERAL]
    "670b57ab": ("Mass", "kg", "Vehicle mass without driver/fuel (Veneno 1570).", "proven", True),
    "bbb39f0b": ("Inertia", "kg m^2", "Body inertia (pitch, yaw, roll order as rF: x, y, z).", "proven", True),
    "a0530c50": ("FuelTankPos", "m", "Fuel tank position (x, y, z).", "strong", True),
    "6f70f3c7": ("FuelTankMotion", "N/m, ratio", "Fuel slosh spring and damping ratio (e.g. (750, 0.7)).", "strong", False),
    "38055c3c": ("Symmetric", "bool", "Left/right setup symmetric.", "strong", False),
    "1824eaa8": ("CGHeight", "m", "CG height above the reference plane.", "proven", True),
    "df8d93cf": ("CGRightRange", "fraction", "Weight on the right side (0.5).", "strong", True),
    "beba677b": ("CGRearRange", "fraction", "Rear weight distribution (Lancer 0.41, Camaro 0.435, Veneno 0.57).", "strong", True),
    "869a7797": ("general_869a7797", "", "(0, 0.02, 0).", "unknown", False),
    "5b5ec8cd": ("WedgeRange", "", "Wedge setup range.", "strong", False),
    "85755f8a": ("WedgeWheel", "", "", "strong", False),
    "86ae662b": ("undertray_params", "N/m, N/(m/s), friction", "Undertray contact (spring, damper, friction) used with the Undertray points (Veneno (300000, 2000, 0.5)).", "strong", False),
    "19389974": ("FuelRange", "litres", "Fuel load range (1, 1, max): the tank capacity is start + step * count.", "strong", True),
    "99f0bbf8": ("FuelSetting", "index", "Default fuel.", "strong", True),
    "965bffbf": ("FeelerFlags", "", "Collision feeler flags.", "strong", False),
    "3a1796c2": ("Notes", "", "", "strong", False),
    "b91b6f6e": ("Rules", "", "", "strong", False),
    # aero
    "ad3c2013": ("FWRange", "start, step, count", "Front wing setup range.", "strong", True),
    "06a31f94": ("FWSetting", "index", "", "strong", True),
    "09a852d9": ("FWMaxHeight", "m", "Ride height where the front wing ground effect stops.", "strong", False),
    "2cfb70da": ("FWDragParams", "coeff (base, per setting, per setting^2)", "Front wing drag in the same units as BodyDragBase.", "strong", True),
    "23ec212a": ("FWLiftParams", "coeff (base, per setting, per setting^2)", "Front wing lift; negative = downforce (Veneno -0.232, F1 -0.372, Lancer +0.032).", "strong", True),
    "a13eb25a": ("FWDraftLiftMult", "factor", "Front wing lift loss in the draft (0.6-1.6).", "guess", False),
    "06f458ac": ("FWLiftHeight", "", "Front wing lift vs height.", "guess", False),
    "96d38a17": ("FWLiftSideways", "", "Front wing lift vs sideslip.", "guess", False),
    "bead3d21": ("FWLiftPeak", "", "Front wing lift peak (angle, factor).", "guess", False),
    "546ccdbf": ("FWLeft", "coeff", "Front wing aero force for leftward airflow (rF xxLeft/Right/Up/Down/Aft/Fore = aero response per flow direction).", "strong", False),
    "c519770c": ("FWRight", "coeff", "", "strong", False),
    "cd985a4c": ("FWUp", "coeff", "", "strong", False),
    "826ed8e3": ("FWDown", "coeff", "", "strong", False),
    "e43e99d8": ("FWAft", "coeff", "", "strong", False),
    "f542e878": ("FWFore", "coeff", "", "strong", False),
    "3dfdab72": ("FWRot", "coeff", "", "strong", False),
    "ebdda812": ("FWCenter", "m", "Front wing centre of pressure (x, y, z).", "strong", True),
    "15765486": ("RWRange", "start, step, count", "Rear wing setup range.", "strong", True),
    "8a98eb35": ("RWSetting", "index", "", "strong", True),
    "67dcb6b3": ("RWDragParams", "coeff (base, per setting, per setting^2)", "Rear wing drag.", "strong", True),
    "83d385b9": ("RWLiftParams", "coeff (base, per setting, per setting^2)", "Rear wing lift; negative = downforce.", "strong", True),
    "6db23390": ("RWDraftLiftMult", "factor", "", "guess", False),
    "7a8f77c8": ("RWLiftHeight", "", "", "guess", False),
    "45481d86": ("RWLiftPeak", "", "", "guess", False),
    "343ec42f": ("RWLeft", "coeff", "", "strong", False),
    "423bc26a": ("RWRight", "coeff", "", "strong", False),
    "efb4240a": ("RWUp", "coeff", "", "strong", False),
    "65f81422": ("RWDown", "coeff", "", "strong", False),
    "69eced3e": ("RWAft", "coeff", "", "strong", False),
    "d507f8fe": ("RWFore", "coeff", "", "strong", False),
    "084b50b3": ("RWRot", "coeff", "", "strong", False),
    "1744ed31": ("RWCenter", "m", "Rear wing centre of pressure.", "strong", True),
    "3363edfd": ("BodyDragBase", "N/(m/s)^2 = 0.5*rho*Cd*A", "Body drag coefficient. Drag force ~ value * v^2, so value = 0.6125 * Cd * A (Lancer 0.44 -> CdA 0.72; GT3 0.414 + wings). For a Cd 0.219, A 2.3 m^2 road car: 0.31.", "strong", True),
    "67caa092": ("body_lift_or_drag_height", "", "Body aero coefficient (Lancer 0.1, Veneno 0.35, Camaro 0.5, F1 0.6). Positive on downforce cars, so probably not plain lift: drag/lift height sensitivity or BodyMaxHeight-like.", "guess", True),
    "1f13c185": ("bodyaero_1f13c185", "", "0 on nearly all cars (0.6 Formula Vee).", "unknown", False),
    "56e0a3ab": ("bodyaero_56e0a3ab", "m?", "0.125-0.2: body aero reference height?", "guess", False),
    "c5a54ece": ("BodyLeft", "coeff", "Body aero response to leftward flow.", "strong", False),
    "6a082ad4": ("BodyRight", "coeff", "", "strong", False),
    "dc57d248": ("BodyUp", "coeff", "", "strong", False),
    "e3a16597": ("BodyDown", "coeff", "", "strong", False),
    "08b1b650": ("BodyAft", "coeff", "Body aero response to rearward flow (x, lift, drag): (0, 0.4, -0.8) on the Lancer.", "strong", False),
    "dc2f52e4": ("BodyFore", "coeff", "", "strong", False),
    "f82631a8": ("BodyRot", "coeff", "", "strong", False),
    "38d18ee7": ("BodyCenter", "m", "Body centre of pressure.", "strong", True),
    "8e02d167": ("radiator_range", "start, step, count", "Radiator opening setup range (0, 5, 20) / (100, 0, 0); f7cf3ca8 = setting.", "guess", False),
    "f7cf3ca8": ("radiator_setting", "index", "", "guess", False),
    "cd9bd54e": ("radiator_drag", "coeff", "Drag per radiator step (0.0002).", "guess", False),
    "0a98aabd": ("radiator_lift", "coeff", "", "guess", False),
    "67643931": ("brake_duct_range", "start, step, count", "Brake duct setup range; cf013571 = setting.", "guess", False),
    "cf013571": ("brake_duct_setting", "index", "", "guess", False),
    "502dc5ae": ("brake_duct_drag", "coeff", "", "guess", False),
    "b728363e": ("brake_duct_lift", "coeff", "", "guess", False),
    "e9ded999": ("Undertray00", "m", "Body/ground contact (scrape) point. NOT the axle (doc 09's 'reference points').", "proven", True),
    "ba614262": ("Undertray01", "m", "Undertray contact point.", "proven", True),
    "ac8de939": ("Undertray02", "m", "Undertray contact point.", "proven", True),
    "c7c23d06": ("Undertray03", "m", "Undertray contact point.", "proven", True),
    "f3141524": ("Undertray04", "m", "Undertray contact point.", "proven", True),
    "12409d39": ("Undertray05", "m", "Undertray contact point.", "proven", True),
    "fb50f76f": ("Undertray06", "m", "Undertray contact point.", "proven", True),
    "42341859": ("Undertray07", "m", "Undertray contact point.", "proven", True),
    "a243c615": ("Undertray08", "m", "Undertray contact point.", "proven", True),
    "e4f96117": ("Undertray09", "m", "Undertray contact point.", "proven", True),
    "6860eb06": ("Undertray10", "m", "Undertray contact point.", "proven", True),
    "9d8f09c3": ("Undertray11", "m", "Undertray contact point.", "proven", True),
    # suspension section
    "e5b9a9d6": ("FrontAntiSwayRange", "N/m", "Front anti-roll bar range; 7fc758d5 = setting.", "strong", True),
    "7fc758d5": ("FrontAntiSwaySetting", "index", "", "strong", True),
    "66001e25": ("RearAntiSwayRange", "N/m", "Rear anti-roll bar range; 0478e991 = setting.", "strong", True),
    "0478e991": ("RearAntiSwaySetting", "index", "", "strong", True),
    "69d49b3b": ("FrontToeInRange", "deg", "Front toe range; c33657cc = setting.", "strong", True),
    "c33657cc": ("FrontToeInSetting", "index", "", "strong", True),
    "55c9ea65": ("RearToeInRange", "deg", "Rear toe range; fdf7434f = setting.", "strong", True),
    "fdf7434f": ("RearToeInSetting", "index", "", "strong", True),
    "1a73fe3e": ("LeftCasterRange", "deg", "Caster range; ffd7a7d9 = setting.", "strong", True),
    "ffd7a7d9": ("LeftCasterSetting", "index", "", "strong", True),
    "33763373": ("RightCasterRange", "deg", "Caster range; a6b8e38f = setting.", "strong", True),
    "a6b8e38f": ("RightCasterSetting", "index", "", "strong", True),
    "b2b49340": ("AlignWheels", "bool", "", "strong", False),
    "d4013a96": ("third_spring_front_range", "N/m", "Front third (heave) spring range (formula cars).", "guess", False),
    "3767ff12": ("third_spring_rear_range", "N/m", "Rear third spring range.", "guess", False),
    # [CONTROLS]
    "f734a1fe": ("steering_wheel_range", "deg", "Steering wheel rotation lock to lock (900 road, 540 GT, 450 F1).", "strong", False),
    "3043ce21": ("SteerLockRange", "deg", "Front wheel steering lock range (18, 0.5, 24); b7c2c57e = setting.", "strong", True),
    "b7c2c57e": ("SteerLockSetting", "index", "", "strong", True),
    "a6321357": ("RearBrakeRange", "fraction", "Brake bias as the REAR fraction, range (0, 0.01, 100); fdba6473 = setting.", "strong", True),
    "fdba6473": ("RearBrakeSetting", "index", "Default brake bias: rear fraction = 0.01 * setting (Lancer 35 % rear, Veneno 45 %).", "strong", True),
    "d0003859": ("BrakePressureRange", "fraction", "Brake pressure (max pedal force) range (0.5, 0.01, 50); dabdb981 = setting. All cars 40 -> 0.90.", "strong", True),
    "dabdb981": ("BrakePressureSetting", "index", "Default brake pressure: 0.5 + 0.01 * setting.", "strong", True),
    "964b29b4": ("HandbrakePressRange", "fraction", "Handbrake pressure range; 52301fd2 = setting.", "strong", False),
    "52301fd2": ("HandbrakePressSetting", "index", "", "strong", False),
    "b3d2e5a0": ("TractionControlRange", "level", "TC level range (0, 0.099, 10) on cars with TC; (0.9, 0, 0) on cars without. 639d2bd2 = default level.", "strong", True),
    "639d2bd2": ("TractionControlSetting", "index", "Default TC level (Lancer 6, Veneno 8, Senna 10; null on cars without TC).", "strong", True),
    "aaadda30": ("tc_params", "", "TC parameters (1, 0.01..0.1).", "guess", False),
    "8b0af94e": ("tc_slip_window", "", "(0.45..0.7, 1).", "guess", False),
    "6eddb480": ("tc_6eddb480", "", "Only on TC cars: 45-65.", "guess", False),
    "b18e1110": ("tc_b18e1110", "", "Only on TC cars: 300-400.", "guess", False),
    "104e1859": ("tc_104e1859", "", "Only on TC cars: 0.75-0.95.", "guess", False),
    "e482835a": ("tc_e482835a", "", "Only on TC cars: 15-40.", "guess", False),
    "07f76e47": ("ABSSlip1", "slip", "ABS target slip (0.04, 0.05).", "strong", False),
    "255afb23": ("ABSSlip2", "slip", "ABS target slip, second map.", "strong", False),
    "249e0313": ("ABSStrength", "level", "ABS level range (0, 0.1, 10) on ABS cars; (0.96, 0, 0) on cars without. b2be8e7e = default level.", "strong", True),
    "b2be8e7e": ("ABSSetting", "index", "Default ABS level (8 on all ABS cars).", "strong", True),
    "26075add": ("ABSMinMax", "", "ABS pressure release limits (0.8, 1).", "strong", False),
    "bc1266e0": ("ABSstandard", "bool", "ABS fitted as standard (1; null on cars without ABS).", "strong", True),
    "bc907f88": ("TCstandard", "bool", "Traction control fitted as standard.", "strong", True),
    "f29af810": ("SCstandard", "bool", "Stability control fitted as standard (null on all base cars).", "strong", True),
    "bdc165d8": ("BrakeByWire", "bool", "", "strong", False),
    "14a8821e": ("ThirdBrake", "", "", "strong", False),
    "01c18b82": ("controls_01c18b82", "int", "+-1190..5160, sign varies (FFB / steering torque?).", "unknown", False),
    "52fa3411": ("controls_52fa3411", "", "5.5-9.4.", "unknown", False),
    # [ENGINE]
    "a3bf1e60": ("torque_mult", "factor", "Torque multiplier on the torque table at low rpm, multiplied with the engine file's a3bf1e60. The game blends this and power_mult with a Gaussian weight around the peak-power rpm. Lancer R 0.85, Camaro 1.04, most cars 1.0. rF GeneralTorqueMult, but the hash doesn't match that name.", "proven", True),
    "c3667d2e": ("power_mult", "factor", "Torque multiplier near and above the peak-power rpm (chassis x engine value). Lancer R 0.85. rF GeneralPowerMult.", "proven", True),
    "27844d75": ("engine_brake_mult", "factor", "Multiplier on the engine-braking (negative) torque column (chassis x engine value). rF GeneralEngineBrakeMult.", "proven", True),
    # [DRIVELINE]
    "9435f2cb": ("WheelDrive", "string offset", "Driven wheels string REAR / FOUR / FRONT (string table; ev.strings_of).", "proven", True),
    "366e8707": ("BaulkTorque", "Nm", "Synchro baulk torque.", "strong", False),
    "2e33db70": ("ClutchTorque", "Nm", "Clutch torque capacity (often = BaulkTorque).", "guess", False),
    "d31cf6c6": ("ClutchInertia", "kg m^2", "0.005-0.05.", "guess", False),
    "7473b200": ("AutoLift", "bool", "Auto throttle lift on upshift.", "strong", False),
    "b519ef5c": ("AutoBlip", "bool", "Auto throttle blip on downshift.", "strong", False),
    "b9e11402": ("AntiStall", "bool", "Anti-stall.", "strong", False),
    "7e93968c": ("ClutchWear", "", "", "strong", False),
    "c4f7e793": ("ShiftDamage", "", "", "strong", False),
    "ff0c2207": ("ForwardGears", "count", "Forward gear count (Veneno 7, Lancer 5, Camaro 6).", "strong", False),
    "d06b69f2": ("diff_d06b69f2", "", "1000-14000: diff pump / preload torque?", "guess", False),
}
for _k, _v in _CORNER.items():
    _C.setdefault(_k, _v)

_G = {  # gearbox .gdfbin
    "88de240f": ("forward_gears", "", "Object: the forward gears (repeated Ratio entries).", "proven", False),
    "9765b7af": ("final_drive", "", "Object: bevel + final drive ratio options.", "proven", False),
    "9d58f964": ("Ratio", "cogs (driver, driven)", "Gear ratio as cog counts; ratio = driven / driver. Write cogs > 127 as i32 (u8 is read signed).", "proven", True),
    "3c5bef62": ("bevel", "cogs", "Bevel gear pair (multiplies the final drive).", "proven", True),
    "4dcf63c6": ("cutGears", "", "1 gearbox: number of gears removed?", "guess", False),
    "670b57ab": ("Mass", "kg", "1 gearbox only.", "strong", False),
    "bbb39f0b": ("Inertia", "kg m^2", "1 gearbox only.", "strong", False),
}

_S = {  # suspension .sdfbin
    "7817b5d2": ("[BODY]", "", "Rigid body (chassis parts, uprights, wheels).", "proven", False),
    "8adfea7e": ("hinge", "", "Hinge joint (wheel spin axle).", "proven", False),
    "2f5a4bdb": ("[BAR]", "", "Link / bar between two bodies.", "proven", False),
    "3a1e187c": ("Name", "string offset", "Body name (offset into the string table).", "proven", False),
    "670b57ab": ("Mass", "kg", "Body mass.", "proven", True),
    "bbb39f0b": ("Inertia", "kg m^2", "Body inertia.", "proven", True),
    "4209feea": ("Pos", "m", "Body position / link point on the positive body.", "proven", True),
    "aab5db49": ("Ori", "rad?", "Body orientation.", "proven", False),
    "9f9074d0": ("posbody", "body id", "Positive body of a link or hinge (0 = chassis).", "proven", False),
    "8a1e5909": ("negbody", "body id", "Negative body.", "proven", False),
    "5a44c7e0": ("neg", "m", "Link point on the negative body.", "proven", True),
    "a213897d": ("axis", "unit vector", "Hinge axis.", "proven", False),
}

_CL = {  # clutch .cmfbin
    "cd660dcb": ("TorqueCap", "Nm", "Clutch torque capacity.", "proven", True),
    "f14ae0c2": ("SlipFactor", "", "Clutch slip factor.", "strong", True),
    "bbb39f0b": ("Inertia", "kg m^2", "Clutch inertia.", "strong", True),
    "fd0aa8d7": ("WearRate", "", "", "strong", False),
    "1f8808b9": ("WearBuffer", "", "", "strong", False),
    "cde6ead4": ("FailLimits", "", "", "strong", False),
    "18928121": ("Flash", "", "", "strong", False),
    "b9e72e24": ("Burst", "", "", "strong", False),
    "fc9d8f36": ("Heating", "", "", "strong", False),
    "d13fe81c": ("WearEffMult", "", "", "strong", False),
    "323face0": ("clutch_temps", "degC...", "(206, 450, 450, 0.004): temperature points (optimum / fail) and coefficient.", "guess", False),
}

_F = {  # failures .fmfbin
    "950f6aef": ("CoolantLeak", "", "Failure model parameters.", "strong", False),
    "ab4ce47f": ("OilLeak", "", "", "strong", False),
    "2edd3e7b": ("Misfires", "", "", "strong", False),
    "7626aacc": ("LooseWheel", "", "", "strong", False),
    "173a1027": ("FWDetach", "", "Front wing detach.", "strong", False),
    "c33fe2b1": ("RWDetach", "", "Rear wing detach.", "strong", False),
}

_T = {  # turbo .tbfbin
    "565025f9": ("Twin Turbo", "bool", "Second turbo present.", "proven", False),
    "76417e95": ("Turbo1 Size", "", "", "strong", True),
    "48f93fc8": ("Turbo2 Size", "", "", "strong", True),
    "9e46ba12": ("SurgeSlope", "", "", "strong", False),
}

_TY = {  # tyres .hdtbin (doc 13)
    "b31155cd": ("DryLatLong", "mu (lat, long)", "Dry friction coefficient (lateral, longitudinal) of a compound: the main grip knob of a tyre set.", "strong", True),
    "b1033b86": ("WetLatLong", "mu (lat, long)", "Wet friction coefficients.", "strong", True),
    "55d45fc5": ("LatPeak", "slip", "Lateral peak slip.", "strong", True),
    "1e7dcbc9": ("LongPeak", "slip", "Longitudinal peak slip.", "strong", True),
    "46ef767a": ("LoadSens", "", "Grip load sensitivity.", "strong", True),
    "62a406ea": ("DrySlide", "", "Sliding friction (dry).", "strong", True),
    "6375b171": ("WetSlide", "", "Sliding friction (wet).", "strong", True),
    "bd034c23": ("Width", "m", "Tread width per axle (not the radius; that is in the vdfm, doc 13).", "proven", False),
    "9a92d44e": ("SpringBase", "N/m", "Tyre vertical spring base.", "strong", False),
    "1cd510df": ("SpringkPa", "N/m per kPa", "Tyre spring vs pressure.", "strong", False),
    "abd65996": ("Damper", "", "Tyre damping.", "strong", False),
    "fc9d8f36": ("Heating", "", "", "strong", False),
    "fd0aa8d7": ("WearRate", "", "", "strong", False),
    "3a1e187c": ("Name", "string offset", "Tyre-set / compound name.", "proven", False),
    "b00f439a": ("[COMPOUND]", "", "Compound section.", "proven", False),
    "1a274f8d": ("[SLIPCURVE]", "", "Slip curve section.", "proven", False),
    "3f5072d6": ("AIGripMult", "factor", "AI grip multiplier.", "strong", False),
}

_B = {}  # boost .bbfbin -- filled from ev.BOOST_KEYS below


def _build():
    from . import ev
    for k, (desc, conf) in ev.BOOST_KEYS.items():
        c = {"loader": "proven", "high": "strong", "medium": "strong", "low": "guess"}.get(conf, "guess")
        name = HASH_NAMES.get(k) or desc.split(",")[0].split("(")[0].strip()
        _B[k] = (name, "", desc, c, k in ev._FIELD.values() or k == "d52a5024")
    for k, n in HASH_NAMES.items():
        if k in SURVEY.get("boost", {}) and k not in _B:
            _B[k] = (n, "", "", "guess", False)
    raw = {"engine": _E, "chassis": _C, "gearbox": _G, "suspension": _S, "clutch": _CL, "failures": _F,
           "turbo": _T, "tyres": _TY, "boost": _B}
    out = {}
    for kind, d in raw.items():
        kd = {}
        for k, (name, unit, desc, conf, edit) in d.items():
            src = "hash" if key_for_name(name) == k else ("descriptive" if name.islower() else "analogy")
            kd[k] = {"name": name, "unit": unit, "desc": desc, "confidence": conf, "editable": bool(edit),
                     "name_source": src}
        # hash-proven names of keys we did not describe
        for k, n in HASH_NAMES.items():
            if k in SURVEY.get(kind, {}) and k not in kd:
                kd[k] = {"name": n, "unit": "", "desc": "Name proven by the key hash; meaning not studied.",
                         "confidence": "guess", "editable": False, "name_source": "hash"}
        out[kind] = kd
    return out


FIELDS = _build()


def _norm_key(key) -> str:
    if isinstance(key, int):
        return shcb.key_hex(key)
    return str(key).lower().replace(" ", "")


def describe(kind: str, key) -> dict:
    """Entry for ``key`` (hex string or int) in a file of ``kind``. Unknown keys get an entry built from
    the base-car survey (``confidence: "unknown"``, ``name: None``)."""
    if kind not in KINDS:
        raise ValueError(f"unknown file kind {kind!r}; expected one of {KINDS}")
    k = _norm_key(key)
    e = FIELDS[kind].get(k)
    if e is not None:
        return dict(e, key=k)
    s = SURVEY.get(kind, {}).get(k)
    if s is not None:
        sec, typ, n, ex = s
        secname = FIELDS[kind].get(sec, {}).get("name") or HASH_NAMES.get(sec) or sec
        desc = f"Unidentified. In {n} of {SURVEY[kind]['_files']} base files" + \
               (f", section {secname}" if sec else "") + f", type {typ}, e.g. {ex}."
    else:
        desc = "Not present in any base-game file."
    return {"key": k, "name": None, "unit": "", "desc": desc, "confidence": "unknown", "editable": False,
            "name_source": None}


def kind_of_path(path: str) -> str | None:
    p = str(path).lower()
    for ext, kind in EXT_KIND.items():
        if p.endswith(ext):
            return kind
    return None


def _value_of(v: shcb.Value):
    if v.type == shcb.T_TUPLE:
        return list(v.value)
    return v.value


def _type_of(v: shcb.Value) -> str:
    if v.type == shcb.T_TUPLE:
        return "tuple[" + ",".join(shcb.CODE_NAMES[c] for c in v.codes) + "]"
    return shcb.TYPE_NAMES.get(v.type, str(v.type))


def list_fields(kind: str, data) -> list:
    """Every keyed value in a physics file, in file order.

    Each item: ``index`` (entry index in ``ShcbFile.entries``), ``member`` (index inside a group or None),
    ``path`` (e.g. ``"[FRONTLEFT]"``, ``"[BODY]#3"``, ``"[BAR]#2/group"``; ``""`` at top level), ``section``
    (object key or None), ``key``, ``name`` (None if unknown), ``type``, ``value``, ``unit``, ``desc``,
    ``confidence``, ``editable``, ``occurrence`` (n-th time this key appears in this path).
    ``data`` is bytes or a parsed :class:`shcb.ShcbFile`."""
    f = shcb.parse(bytes(data)) if isinstance(data, (bytes, bytearray)) else data
    out = []
    total = {}
    for x in f.entries:
        if isinstance(x, shcb.Object):
            total[x.key] = total.get(x.key, 0) + 1
    obj_count = {}
    path, section = "", None
    seen = {}
    for i, e in enumerate(f.entries):
        if isinstance(e, shcb.Object):
            section = shcb.key_hex(e.key)
            label = describe(kind, section)["name"] or section
            n = obj_count.get(e.key, 0)
            obj_count[e.key] = n + 1
            path = label if total[e.key] == 1 else f"{label}#{n}"
            continue
        if isinstance(e, shcb.Value):
            members = [(None, e)]
        elif isinstance(e, shcb.Group):
            members = list(enumerate(e.members))
        else:
            out.append({"index": i, "member": None, "path": path, "section": section, "key": None, "name": None,
                        "type": "raw", "value": e.data.hex(), "unit": "", "desc": "Unparsed bytes.",
                        "confidence": "unknown", "editable": False, "occurrence": 0})
            continue
        for j, v in members:
            k = shcb.key_hex(v.key)
            d = describe(kind, k)
            p = path + ("/group" if j is not None else "")
            occ = seen.get((p, k), 0)
            seen[(p, k)] = occ + 1
            out.append({"index": i, "member": j, "path": p, "section": section, "key": k, "name": d["name"],
                        "type": _type_of(v), "value": _value_of(v), "unit": d["unit"], "desc": d["desc"],
                        "confidence": d["confidence"], "editable": d["editable"], "occurrence": occ})
    return out


def setup_value(rng, setting):
    """Effective value of a ``Range = (start, step, count)`` + ``Setting`` pair."""
    start, step = float(rng[0]), float(rng[1]) if len(rng) > 1 else 0.0
    return start + step * (setting or 0)

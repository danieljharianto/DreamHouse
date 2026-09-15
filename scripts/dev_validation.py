"""Local development validator stub for DreamHouse.

NOT the official benchmark validator. The real structural-engineering rules
are proprietary and distributed separately (see README "Running the server
locally"). This stub implements `completeness` for real, derived from the
documented member-naming convention (README "Member Naming" table); every
other test always passes so the full harness plumbing (task fetch -> Blender
generation -> export -> validation) can be exercised without the official
artifact.

Interface required by server/_blender_script.py:
    run_all_tests(collection: bpy.types.Collection) -> dict

Install with:
    python scripts/install_validator.py scripts/dev_validation.py
"""

_CATEGORY_KEYWORDS = {
    "foundation": ["sill", "post", "beampost", "foundation"],
    "floor": ["centerbeam", "rim", "joist"],
    "walls": ["plate", "stud", "king", "trimmer", "header", "cripple"],
    "roof": ["ridge", "rafter", "raf", "collar", "lookout", "purlin", "valley", "hip"],
}


def _categorize(name):
    lowered = name.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return None


def run_all_tests(collection):
    categories_present = {
        cat for obj in collection.objects if (cat := _categorize(obj.name))
    }
    completeness = {"foundation", "floor", "walls", "roof"}.issubset(categories_present)

    tests = {
        "completeness": completeness,
        "load_path": True,
        "span_limits": True,
        "deflection": True,
        "roof_coverage": True,
        "gap_detection": True,
        "point_load": True,
        "cantilever": True,
        "stability_score": True,
        "dual_end_connection": True,
    }
    return {"all_passed": all(tests.values()), **tests}

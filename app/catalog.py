"""Curated reading of the corpus.

PDF text comes out as an unordered stream, so titles, BOM links, and the three
solid reconstructions are written down here after reading each sheet. Extraction
refuses to build if a quote in this file is not actually in the source text.
Degraded sheets have no quotes: their titles come from the filename only.
"""

from __future__ import annotations

# Drawing subsystem names and the BOM family names are not the same vocabulary.
SUBSYSTEM_FAMILIES = {
    "Box": ["Box"],
    "Powder": ["Powder"],
    "Recoater": ["Recoater"],
    "Optical": ["Optics"],
    "Gas Flow": ["Gas flow"],
    "Z-axis": ["Build-plate"],
}

# Titles for sheets with no extractable text. These are filename readings.
FILENAME_TITLES = {
    "D-001": "Door x2",
    "D-003": "Main platform",
    "D-009": "Powder canister",
    "D-011": "Recoater arm",
    "D-020": "F-theta seal ring",
    "D-022": "Inlet box",
    "D-023": "Build cylinder",
    "D-030": "Z-axis motor plate",
}

# Extra phrases a person might type. Each phrase must occur in extracted text
# unless the drawing is degraded, in which case the phrase is a filename alias
# stored separately below.
TEXT_ALIASES = {
    "D-002": ["left wall"],
    "D-004": ["top plate"],
    "D-005": ["window clamp frame", "laser window frame"],
    "D-006": ["canister wall"],
    "D-007": ["dispenser shaft"],
    "D-008": ["powder bracket"],
    "D-010": ["powder motor plate"],
    "D-012": ["recoater mount block"],
    "D-013": ["recoater plate"],
    "D-014": ["recoater linear plate"],
    "D-015": ["silikone wiper", "silicone wiper"],
    "D-016": ["galvo bundplade"],
    "D-017": ["galvo montage plade", "galvo collimator plade"],
    "D-018": ["galvo mount side"],
    "D-021": ["blower outlet", "gas outlet box"],
    "D-024": ["byggebase", "build base"],
    "D-025": ["bygge base ring"],
    "D-026": ["build plate", "byggeplade"],
    "D-027": ["cylinder spaend ring", "cylinder spænd ring"],
    "D-028": ["varmeelement plade", "heating element plate"],
    "D-029": ["z-axis bottomplate", "z-axis bottom plate"],
}

FILENAME_ALIASES = {
    "D-001": ["front door", "back door", "door"],
    "D-003": ["print platform", "main platform"],
    "D-009": ["powder canister", "powder hopper"],
    "D-011": ["recoater arm"],
    "D-020": ["f-theta seal ring", "f-theta seal"],
    "D-022": ["inlet box", "gas flow inlet"],
    "D-023": ["build cylinder"],
    "D-030": ["z-axis motor plate", "motor plate"],
}

# relation: depicts (use it) | candidate (possible, not settled) | rejected (do not merge)
LINKS = [
    ("D-001", "Front Door", "depicts", "medium",
     "The file is Door_x2. Front Door is one of the two door rows. The scan has no text, so the sheet cannot separate front from back."),
    ("D-001", "Back Door", "depicts", "medium",
     "Door_x2 also matches Back Door. Both rows are attached because the degraded sheet does not identify which door is drawn."),
    ("D-002", "Left Side Box", "depicts", "medium",
     "The sheet title is Left Wall and the callout is 2 mm non-magnetic stainless. The BOM name is Left Side Box, also stainless. The names are not identical."),
    ("D-003", "Print Platform", "depicts", "medium",
     "The filename is MainPlatform_Loop2. Print Platform is the BOM row for that structure. The scan has no extractable text."),
    ("D-004", "Top Side", "depicts", "medium",
     "The sheet title is Top Plate, 3 mm non-magnetic stainless. The BOM row is Top Side, stainless steel. Same wall, different names."),
    ("D-005", "Window Frame", "depicts", "high",
     "The title block says Window Clamp Frame and the note says laser window frame. The BOM row is Window Frame."),
    ("D-008", "Powder handling mount bracket", "candidate", "low",
     "Powder Bracket is a stainless sheet. This BOM row is also a custom stainless powder bracket, but the names differ."),
    ("D-008", "Powder stepper bracket", "candidate", "low",
     "Second stainless custom powder row that could be the same bracket. The sheet does not use this name."),
    ("D-009", "Powder hopper", "candidate", "low",
     "Filename PowderCanister versus BOM Powder hopper. Both are powder containers. The scan has no text to confirm the match."),
    ("D-010", "Motor plate", "rejected", "high",
     "The build-plate Motor plate is aluminium and holds three non-captive steppers. D-010 is filed as PowderMotorPlate and calls out 2 mm non-magnetic stainless. Shared words, conflicting materials."),
    ("D-010", "Powder stepper bracket", "candidate", "low",
     "Closest custom stainless part in the powder family. The drawing never uses that name, so the link stays a candidate."),
    ("D-011", "Recoater Arm", "depicts", "high",
     "Filename RecoaterArm matches the BOM name. The distributed sheet is a degraded scan with no extractable text."),
    ("D-012", "Recoater mount block", "depicts", "high",
     "Title block Recoater Mount Block matches the BOM row. The sheet also says montage block for the linear guide."),
    ("D-013", "Recoater head", "depicts", "medium",
     "Title block Recoater Plate. The Recoater head row cites RecoaterPlate.pdf. The note calls it an adjustment plate, so the function is not word-for-word the BOM design intent."),
    ("D-014", "Recoater stage plate", "depicts", "high",
     "Filename RecoaterStagePlate and the note 'plate for the linear guide' match the stage plate, which mounts on the linear bearings. The title block says Recoater Linear Plate."),
    ("D-015", "Recoater Blade", "depicts", "high",
     "The sheet is a 270 mm silicone wiper, 1 mm thick. The Recoater Blade row describes a 1 mm silicone sheet and cites Silicone270mm_1mm_x2.pdf."),
    ("D-016", "Sunny Galvo Adapter Plate", "candidate", "low",
     "Title block Galvo Bundplade (galvo bottom plate). The BOM has no row with that name. Sunny Galvo Adapter Plate is only a possible optics relative."),
    ("D-018", "Galve support bracket", "candidate", "low",
     "Galvo Mount Side is a 7075-T6 aluminium plate. The BOM support bracket is typed Galve and recorded as stainless steel and steel, so the materials do not agree."),
    ("D-019", "Silicone gasket f-theta ring", "depicts", "high",
     "Filename SiliconePakningfTheta and the note '1 mm silicone gasket' match this BOM row. The title block itself only says Description."),
    ("D-020", "F-theta seal ring", "depicts", "high",
     "Filename f-theta-SealRing matches the BOM row. The sheet is degraded and has no extractable text."),
    ("D-021", "Gas flow end duct", "rejected", "high",
     "Blower Outlet is non-magnetic stainless and welded. Gas flow end duct is recorded as polymer. The names also differ."),
    ("D-022", "Gas flow inlet geometry", "candidate", "low",
     "Filename InletBox versus Gas flow inlet geometry. The scan has no text, and the BOM material cell is blank."),
    ("D-023", "Build cylinder", "depicts", "high",
     "Filename BuildCylinder_v2 matches the BOM row. The sheet is degraded. The BOM design intent gives OD 280 and ID 252; the drawing text cannot confirm them."),
    ("D-024", "Build base", "depicts", "high",
     "Title block ByggeBase is the Danish name for the build base."),
    ("D-026", "Build Plate", "depicts", "high",
     "Title block Build Plate matches the BOM row. The sheet note says stainless and aluminium, one to three of each."),
    ("D-027", "Build cylinder clamp ring", "depicts", "high",
     "Title block Cylinder Spænd Ring and the filename match the clamp ring that holds the build cylinder."),
    ("D-028", "Heating element plate", "depicts", "high",
     "Title block Varmeelement Plade is the Danish name. The note says three pieces, and the BOM amount is 3."),
    ("D-030", "Motor plate", "depicts", "medium",
     "Filename Z-axis_MotorPlate matches the build-plate motor plate. The scan has no text, so the aluminium callout in the BOM is not confirmed by this sheet."),
]

# Quotes that must be substrings of the extracted text (spaces ignored, comma or dot).
DRAWING_QUOTES = {
    "D-002": ["Left Wall", "2mm non-magnetic stainless"],
    "D-004": ["Top Plate", "3 mm non-magnetic stainless"],
    "D-005": ["Window Clamp Frame", "6061 Alloy", "Holds 210x297mm", "323,0", "236,0", "297,2", "210,2", "8,2"],
    "D-006": ["Canister Wall", "3mm (or thicker)"],
    "D-007": ["Dispenser Shaft v6", "336,1", "269,5", "29,0", "37,6", "8,0 g8", "25,0"],
    "D-008": ["Powder Bracket", "2-3mm non-magnetic stainless"],
    "D-010": ["Motor Plate", "2mm non-magnetic stainless", "107,00", "70,00"],
    "D-012": ["Recoater Mount Block", "Montage klods til linæer føring"],
    "D-013": ["Recoater Plate", "Justeringsplade til recoater"],
    "D-014": ["Recoater Linear Plate", "Plade til linæer føring"],
    "D-015": ["Silikone Wiper", "silikone plade"],
    "D-016": ["Galvo Bundplade"],
    "D-017": ["Galvo Montage Plade", "Galvo Collimator Plade"],
    "D-018": ["Galvo Mount Side x2", "7075-T6"],
    "D-019": ["1mm silicone pakning"],
    "D-021": ["Blower Outlet", "Non-magnetic stainless", "Gas outlet box"],
    "D-024": ["ByggeBase"],
    "D-025": ["Bygge Base Ring"],
    "D-026": ["Build Plate", "AISI 316", "rustfri og alu"],
    "D-027": ["Cylinder Spænd Ring", "6063-T6"],
    "D-028": ["Varmeelement Plade", "3 styk"],
    "D-029": ["Z-axis BottomPlate"],
}

RECONSTRUCTIONS = {
    "D-005": {
        "shape": "frame",
        "title": "Window Clamp Frame",
        "params": {"outer_mm": [323.0, 236.0, 8.2], "opening_mm": [297.2, 210.2]},
        "quotes": ["323,0", "236,0", "297,2", "210,2", "8,2", "Holds 210x297mm"],
        "caveat": (
            "Plan size 323 by 236 mm and opening 297.2 by 210.2 mm are callouts on D-005. "
            "The note 'Holds 210x297mm laser window' is why 297 sits on the long side and 210 on the short side. "
            "Thickness uses the 8.2 callout. Section callouts 3.3 and 2.0, the o-ring grooves, and the 20 M4 holes are not in the solid. "
            "This is a reconstruction from 2D evidence, not native CAD."
        ),
    },
    "D-007": {
        "shape": "shaft",
        "title": "Dispenser Shaft v6",
        "params": {
            "segments_mm": [
                {"length": 29.0, "diameter": 8.0},
                {"length": 269.5, "diameter": 25.0},
                {"length": 37.6, "diameter": 8.0},
            ]
        },
        "quotes": ["336,1", "29,0", "269,5", "37,6", "8,0 g8", "25,0"],
        "caveat": (
            "29.0 + 269.5 + 37.6 equals the 336.1 overall length callout, so those three lengths are the segments. "
            "The sheet calls out 8.0 g8 twice and also 25.0. Putting the 8 mm journals on the short ends is an inference: "
            "the extracted text has no diameter symbol tying 25.0 to the middle. "
            "The three helical grooves are not modeled. This is a reconstruction from 2D evidence, not native CAD."
        ),
    },
    "D-010": {
        "shape": "plate",
        "title": "Powder motor plate",
        "params": {"size_mm": [107.0, 70.0, 2.0]},
        "quotes": ["107,00", "70,00", "2mm non-magnetic stainless"],
        "caveat": (
            "107 mm and 70 mm are the two largest plan callouts. 2 mm is the explicit thickness in '2mm non-magnetic stainless'. "
            "30 mm and 15 mm are smaller and are treated as hole positions, not the envelope. Holes are omitted. "
            "This is a reconstruction from 2D evidence, not native CAD."
        ),
    },
}

# Snippets must appear verbatim in the upstream readme.
README_CLAIMS = [
    {
        "id": "S-BUILD",
        "statement": "The upstream description gives a 250 mm by 150 mm build volume, a 300 W 1080 nm laser, and closed-loop gas-flow cross flow.",
        "snippet": "It features a 250mm x 150mm build volume and a 300W 1080nm laser. It is self-contained and has a closed-loop gas flow cross flow.",
    },
    {
        "id": "S-SAFETY",
        "statement": "The upstream description names an ABB Pluto D20 safety PLC as the safety controller.",
        "snippet": 'The system employs an ABB Pluto D20 safety PLC as its "brain."',
    },
    {
        "id": "S-LICENSE",
        "statement": "The upstream project states that the design is published under CERN-OHL-P v2.",
        "snippet": "The entire design and detailed documentation are published under the CERN-OHL-P (permissive) v2 Open Source Hardware license",
    },
]

"""A synthetic village, so the camp planner has something to plan for.

The planner works over many households at once, and we have five. Rather than
pretend to field data we do not have, this draws a village from the same
schema the rest of the app uses, with the correlations that make a household
plausible: a widow is a woman, an Antyodaya card goes with a low income, a
family with no land does not farm.

It is reproducible from a seed and it is clearly synthetic. Nothing measured
on it is a finding about any real village; it is a load for an algorithm.

    python3 tools/village.py --out data/cases/village.yaml --houses 60
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from patra.encode.loader import load_documents, load_schema  # noqa: E402

# Papers a household is likely to already hold, roughly in the order real
# coverage runs: nearly everyone has Aadhaar, far fewer have a caste
# certificate or land records on paper.
LIKELY = {
    "aadhaar": 0.92, "voter_id": 0.78, "ration_card": 0.70,
    "passport_photo": 0.55, "bank_account": 0.64, "electricity_bill": 0.52,
    "birth_certificate": 0.34, "school_certificate": 0.30,
    "bank_aadhaar_seeding": 0.38, "income_certificate": 0.22,
    "caste_certificate": 0.26, "domicile_certificate": 0.24,
    "land_records": 0.28, "job_card": 0.31, "pan_card": 0.18,
    "disability_certificate": 0.05, "death_certificate": 0.07,
}

NAMES = ["Sunita", "Ramlal", "Munni", "Kishore", "Bhola", "Shanti", "Gulab",
         "Kamla", "Rajesh", "Phoolwati", "Mahesh", "Savitri", "Dinesh",
         "Rukmani", "Jagdish", "Leela", "Suresh", "Chandra", "Ravi", "Anita"]


def household(rng, schema, documents, index):
    rural = rng.random() < 0.88
    land = rng.choice([0, 0, 0, 1, 1, 2, 3, 5, 8]) if rural else 0
    card = rng.choices(["aay", "phh", "apl", "none"],
                       weights=[22, 44, 24, 10])[0]
    income = {
        "aay": rng.randint(18000, 46000),
        "phh": rng.randint(40000, 110000),
        "apl": rng.randint(95000, 260000),
        "none": rng.randint(60000, 300000),
    }[card]

    facts = {
        "state": "haryana",
        "area_type": "rural" if rural else "urban",
        "annual_income": income,
        "ration_card_type": card,
        "land_acres": land,
        "cultivates_land": bool(land) and rng.random() < 0.82,
        "owns_pucca_house": rng.random() < (0.28 if card in ("aay", "phh") else 0.72),
        "owns_vehicle": rng.random() < (0.16 if card == "aay" else 0.44),
        "income_tax_payer": income > 250000 and rng.random() < 0.6,
        "govt_employee_in_family": rng.random() < 0.07,
        "lpg_connection": rng.random() < 0.58,
        "breadwinner_died_recently": rng.random() < 0.05,
    }

    members = []
    size = rng.choices([2, 3, 4, 5, 6, 7], weights=[8, 18, 26, 24, 16, 8])[0]
    for n in range(size):
        if n == 0:
            age = rng.randint(28, 78)
        elif n == 1:
            age = rng.randint(24, 74)
        else:
            age = rng.randint(1, 30)
        gender = rng.choice(["male", "female"])
        married = "unmarried"
        if age >= 20:
            married = rng.choices(["married", "widowed", "unmarried", "divorced"],
                                  weights=[66, 14, 17, 3])[0]
        work = "student" if age < 18 else rng.choices(
            ["farm_labour", "daily_wage", "farmer", "homemaker", "unemployed",
             "self_employed", "salaried"],
            weights=[22, 22, 14 if land else 2, 20, 9, 8, 5])[0]
        member = {
            "id": f"h{index}m{n}",
            "name": f"{rng.choice(NAMES)}",
            "facts": {
                "age": age,
                "gender": gender,
                "marital_status": married,
                "category": rng.choices(["general", "obc", "sc", "st"],
                                        weights=[18, 42, 32, 8])[0],
                "disability_percent": rng.choices([0, 40, 60, 75],
                                                  weights=[93, 3, 2, 2])[0],
                "is_pregnant": (gender == "female" and 19 <= age <= 40
                                and rng.random() < 0.09),
                "occupation": work,
                "willing_unskilled_work": age >= 18 and rng.random() < 0.55,
                "has_bank_account": age >= 15 and rng.random() < 0.66,
                "already_receiving_pension": age >= 60 and rng.random() < 0.34,
            },
        }
        f = member["facts"]
        f["first_child"] = f["is_pregnant"] and rng.random() < 0.4
        f["bank_aadhaar_linked"] = f["has_bank_account"] and rng.random() < 0.55
        members.append(member)

    held = sorted(d for d, chance in LIKELY.items()
                  if d in documents and rng.random() < chance)

    return {"id": f"h{index}", "facts": facts, "members": members,
            "documents": held}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="village", description="Draw a synthetic village to plan for.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--houses", type=int, default=60)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    schema = load_schema(ROOT / "data" / "attributes.yaml")
    documents = load_documents(ROOT / "data" / "documents.yaml")

    import yaml
    houses = [household(rng, schema, documents, i)
              for i in range(1, args.houses + 1)]

    header = (
        "# A synthetic village, drawn by tools/village.py.\n"
        "#\n"
        "# Nothing measured on it is a finding about any real village. It is a\n"
        "# load for the camp planner, reproducible from a seed, and the\n"
        f"# correlations in it are ours: seed {args.seed}, {args.houses} households.\n"
        "#\n"
        "# Regenerate with:\n"
        f"#   python3 tools/village.py --out {args.out} "
        f"--houses {args.houses} --seed {args.seed}\n\n"
    )
    args.out.write_text(
        header + yaml.safe_dump({"households": houses}, allow_unicode=True,
                                sort_keys=False, width=88),
        encoding="utf-8")

    people = sum(len(h["members"]) for h in houses)
    print(f"{len(houses)} households, {people} people -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

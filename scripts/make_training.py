"""Synthetic demo data, not evidence of real-world extraction quality."""

import csv
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "training"

ROLES = [
    "Cloud Engineer", "Software Engineer", "Data Analyst",
    "DevOps Engineer", "Backend Developer", "Frontend Developer",
    "Data Engineer", "Security Analyst", "Platform Engineer",
    "Machine Learning Engineer"
]

SKILLS = [
    "Python", "Java", "Amazon Web Services", "Docker",
    "Kubernetes", "SQL", "PostgreSQL", "JavaScript",
    "React", "Linux", "Git", "Terraform", "Node.js",
    "Pandas", "NumPy", "TensorFlow", "FastAPI",
    "Networking", "Microsoft Azure", "CI/CD"
]


def make(split, count, seed):
    rng = random.Random(seed)
    lines = []
    rows = []

    for i in range(count):
        role = ROLES[i % len(ROLES)]
        skills = rng.sample(SKILLS, 5)
        skill_text = ", ".join(skills)

        if split == "train":
            templates = [
                f"I worked as a {role} at Example Systems. "
                f"My responsibilities included {skill_text}.",

                f"We are hiring a {role}. Required capabilities: "
                f"{skill_text}. Please describe relevant project work.",

                f"Professional summary: {role}. Technical skills: "
                f"{skill_text}. I built and maintained team applications."
            ]
        else:
            templates = [
                f"Position sought: {role}. In recent assignments I used "
                f"{skill_text}. Evidence is available in my portfolio.",

                f"The vacancy is for a {role}; applicants need experience "
                f"with {skill_text}. This is a synthetic evaluation document."
            ]

        line = (
            templates[i % len(templates)]
            + f" Synthetic record {split}-{i:04d}."
        )
        annotations = []

        for entity_type, values in [
            ("JOB_TITLE", [role]),
            ("SKILL", skills)
        ]:
            for value in values:
                pattern = r"(?<!\w)" + re.escape(value) + r"(?!\w)"
                matches = list(re.finditer(pattern, line))

                if len(matches) != 1:
                    raise ValueError(
                        f"{split}, line {i}: expected one exact "
                        f"match for {value!r}, found {len(matches)}"
                    )

                match = matches[0]
                begin, end = match.span()

                if line[begin:end] != value:
                    raise ValueError(
                        f"{split}, line {i}: invalid offsets for {value!r}"
                    )

                annotations.append((begin, end, entity_type))

        annotations.sort()

        for previous, current in zip(annotations, annotations[1:]):
            if previous[1] > current[0]:
                raise ValueError(
                    f"{split}, line {i}: overlapping annotations "
                    f"{previous} and {current}"
                )

        lines.append(line)

        for begin, end, entity_type in annotations:
            rows.append([
                f"{split}.txt", i, begin, end, entity_type
            ])

    folder = ROOT / split
    folder.mkdir(parents=True, exist_ok=True)

    (folder / f"{split}.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8"
    )

    with (ROOT / f"{split}-annotations.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.writer(file)
        writer.writerow([
            "File", "Line", "Begin Offset", "End Offset", "Type"
        ])
        writer.writerows(rows)

    return {
        "documents": len(lines),
        "annotations": len(rows)
    }


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)

    stats = {
        "train": make("train", 300, 41),
        "test": make("test", 100, 79),
        "warning": (
            "Synthetic bootstrap data. Evaluate on independently "
            "annotated, consented real-world-style resumes before use."
        )
    }

    (ROOT / "manifest.json").write_text(
        json.dumps(stats, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(stats, indent=2))
    print("Validation passed: exact entity matches and no overlaps.")
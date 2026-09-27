from collections import Counter
import re
import sys
from typing import Any

from edgedash.config import Config, load_config
import edgedash.storage as storage

DEFAULT_ALIASES: dict[str, str] = {
    "k8s": "kubernetes", "kubernetes": "kubernetes",
    "js": "javascript", "javascript": "javascript",
    "node": "nodejs", "nodejs": "nodejs", "node.js": "nodejs", "node js": "nodejs",
    "postgres": "postgres", "postgresql": "postgres", "psql": "postgres",
    "gcp": "gcp", "google cloud": "gcp", "google cloud platform": "gcp",
    "ml": "machine learning", "machine learning": "machine learning",
    "ci/cd": "ci/cd", "ci cd": "ci/cd", "cicd": "ci/cd", "ci-cd": "ci/cd",
    "react": "react", "react.js": "react", "reactjs": "react",
    "sklearn": "scikit-learn", "scikit-learn": "scikit-learn", "scikitlearn": "scikit-learn", "scikit learn": "scikit-learn",
    "ts": "typescript", "typescript": "typescript", "py": "python", "python": "python",
}


def canonical(raw: str, aliases: dict[str, str] | None = None) -> str:
    """Canonicalize a skill string deterministically (Rules 22, 23)."""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.lower()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = s.strip().strip(" \t\n\r,;:!?\"'`~").rstrip(".-_")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    alias_map = aliases if aliases else DEFAULT_ALIASES
    return alias_map.get(s, s)


def audit_skills(config: Config | None = None) -> None:
    """Read all extracted required_skills in storage and print frequency audit (Rule 23)."""
    cfg = config or load_config()
    alias_map = getattr(cfg, "skill_aliases", None) or DEFAULT_ALIASES
    all_raw = storage.get_all_extracted_skills(db_path=cfg.db_path)
    counts = Counter(all_raw)
    print("=" * 80)
    print("EDGEDASH SKILL CANONICALISATION AUDIT (READ-ONLY)")
    print(f"Total Skill Occurrences: {len(all_raw)} | Unique Raw Strings: {len(counts)}")
    print("=" * 80 + "\nTOP 40 MOST COMMON RAW SKILL STRINGS:")
    print("-" * 80 + f"\n{'Count':<8}{'Raw Skill String':<42}-> Canonical Form\n" + "-" * 80)
    for raw, cnt in counts.most_common(40):
        print(f"{cnt:<8}{raw[:40]:<42}-> {canonical(raw, alias_map)}")
    single_occs = sorted([raw for raw, cnt in counts.items() if cnt == 1])
    print("\n" + "-" * 80 + f"\nSINGLE-OCCURRENCE RAW STRINGS ({len(single_occs)} strings seen only once):\n" + "-" * 80)
    for idx, raw in enumerate(single_occs, 1):
        canon = canonical(raw, alias_map)
        arrow = f" -> {canon}" if canon != raw else ""
        print(f"[{idx:3d}] {raw}{arrow}")


def check_proposal_conflicts(proposal: dict[str, Any], alias_map: dict[str, str]) -> list[str]:
    """Flag proposals that group strings already separated in alias map (Rule 23)."""
    conflicts: list[str] = []
    variants = proposal.get("variants", [])
    prop_canon = proposal.get("canonical", "").strip().lower()
    mapped = {v: alias_map[v] for v in variants if v in alias_map}
    if len(set(mapped.values())) > 1:
        det = ", ".join(f"'{v}' -> '{tgt}'" for v, tgt in mapped.items())
        conflicts.append(f"Groups strings already mapped to different skills: {det}")
    for v, existing_tgt in mapped.items():
        if existing_tgt != prop_canon and f"'{v}' -> '{existing_tgt}'" not in "; ".join(conflicts):
            conflicts.append(f"'{v}' is already mapped to '{existing_tgt}' (proposal suggests '{prop_canon}')")
    return conflicts


def suggest_aliases(config: Config | None = None, llm_module: Any = None) -> None:
    """Propose skill groupings via LLM. Read-only, never modifies files (Rule 23)."""
    cfg = config or load_config()
    alias_map = getattr(cfg, "skill_aliases", None) or DEFAULT_ALIASES
    raw_skills = storage.get_all_extracted_skills(cfg.db_path)
    alias_keys = set(alias_map.keys()) | set(alias_map.values())
    unaliased = [canonical(r, alias_map) for r in raw_skills if canonical(r, alias_map) and canonical(r, alias_map) not in alias_keys]
    counts = Counter(unaliased)
    if not counts:
        print("\n[!] No unaliased skills found in database. All skills are already covered.\n")
        return

    skills_text = "\n".join(f"- {s} ({cnt})" for s, cnt in counts.most_common(120))
    prompt = (
        "You are an expert software/data engineering skills taxonomist.\n"
        "Propose groupings of strings that refer to the exact same underlying skill and should be aliased.\n\n"
        "RULES (Rule 23):\n"
        "1. ONLY group strings that are truly synonymous or language/spelling variants (e.g. deutsch, german -> german).\n"
        "2. DO NOT MERGE DISTINCT SKILLS: Node and JavaScript are DIFFERENT; C and C++ are DIFFERENT; AWS and GCP are DIFFERENT. When in doubt, do NOT merge.\n"
        "3. Output format: schema with key 'proposals', list of objects with 'canonical' (str), 'variants' (list[str] >= 2), 'confidence' ('high'|'low').\n\n"
        f"INPUT SKILLS (with counts):\n{skills_text}\n\n"
        "Return valid JSON: {\"proposals\": [{\"canonical\": \"...\", \"variants\": [\"...\"], \"confidence\": \"high\"|\"low\"}]}"
    )
    mod = llm_module or __import__("edgedash.llm", fromlist=["complete_json"])
    res = mod.complete_json(prompt, {"required": ["proposals"]}, config=cfg)
    proposals = res.get("proposals", []) if isinstance(res, dict) else []

    print("=" * 88)
    print("                EDGEDASH SKILL ALIAS PROPOSALS (SUGGESTIONS ONLY)")
    print("=" * 88)
    print("[!] WARNING: Automated LLM suggestions REQUIRE human review. Merging distinct skills")
    print("    is far worse than leaving them separate. Never auto-merge without review (Rule 23).")
    print("=" * 88)

    valid_yaml: list[str] = []
    conflict_count = 0
    for p in proposals:
        canon, variants, conf = p.get("canonical", ""), p.get("variants", []), p.get("confidence", "low")
        conflicts = check_proposal_conflicts(p, alias_map)
        if conflicts:
            conflict_count += 1
            print(f"\n[!] CONFLICT WITH EXISTING ALIAS MAP (Proposal: '{canon}', Confidence: {conf}):")
            for c in conflicts:
                print(f"    * {c}")
            print("    -> REJECTED: Your existing config.yaml choices take precedence.")
        else:
            valid_yaml.append(f"  # Proposal: {canon} (confidence: {conf})")
            for v in variants:
                v_esc = v.replace('"', '\"')
                c_esc = canon.replace('"', '\"')
                valid_yaml.append(f'  "{v_esc}": "{c_esc}"')
            valid_yaml.append("")

    if valid_yaml:
        print("\n# " + "=" * 80)
        print("# READY-TO-PASTE config.yaml ALIAS MAP ENTRIES (Review before adding):")
        print("# " + "=" * 80)
        print("\n".join(valid_yaml))
    else:
        print("\nNo valid non-conflicting proposals generated.")
    print(f"Total proposals: {len(proposals)} | Valid: {len(proposals) - conflict_count} | Conflicts: {conflict_count}\n")


if __name__ == "__main__":
    if "--audit" in sys.argv:
        audit_skills()
    elif "--suggest-aliases" in sys.argv:
        suggest_aliases()
    else:
        print("Usage: python -m edgedash.skills [--audit | --suggest-aliases]")

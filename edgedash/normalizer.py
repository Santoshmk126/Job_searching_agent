import re
from typing import Any

# Canonical alias mapping for developer technologies
SKILL_ALIASES: dict[str, str] = {
    # Node / JavaScript / TypeScript
    "node": "nodejs",
    "node.js": "nodejs",
    "nodejs": "nodejs",
    "node js": "nodejs",
    "react": "react",
    "react.js": "react",
    "reactjs": "react",
    "react js": "react",
    "vue": "vue",
    "vue.js": "vue",
    "vuejs": "vue",
    "vue js": "vue",
    "angular": "angular",
    "angular.js": "angular",
    "angularjs": "angular",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    # Python & ML / Data
    "py": "python",
    "python": "python",
    "python3": "python",
    "sklearn": "scikit-learn",
    "scikit-learn": "scikit-learn",
    "scikitlearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "pytorch": "pytorch",
    "torch": "pytorch",
    "tf": "tensorflow",
    "tensorflow": "tensorflow",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "golang": "go",
    "go": "go",
    "cpp": "c++",
    "c++": "c++",
    "csharp": "c#",
    "c#": "c#",
    "dotnet": ".net",
    ".net": ".net",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "gcp",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "azure": "azure",
    "microsoft azure": "azure",
    "ci/cd": "cicd",
    "ci-cd": "cicd",
    "cicd": "cicd",
    "ci cd": "cicd",
    "ml": "machine learning",
    "machine learning": "machine learning",
    "dl": "deep learning",
    "deep learning": "deep learning",
    "ai": "ai",
    "artificial intelligence": "ai",
    "nlp": "nlp",
    "natural language processing": "nlp",
    "cv": "computer vision",
    "computer vision": "computer vision",
    "llm": "llms",
    "llms": "llms",
    "large language models": "llms",
    "genai": "generative ai",
    "generative ai": "generative ai",
}


def normalize_skill(skill: Any) -> str:
    """Canonicalize a skill name across case, whitespace, punctuation, and aliases.

    Guarantees that 'Node.js', 'nodejs', and 'node' all map to 'nodejs'.
    """
    if not skill or not isinstance(skill, str):
        return ""

    cleaned = skill.strip().lower().rstrip(",;:")
    cleaned = re.sub(r"\s+", " ", cleaned)

    if not cleaned:
        return ""

    if cleaned in SKILL_ALIASES:
        return SKILL_ALIASES[cleaned]

    simplified = re.sub(r"[\s\.\-_/]+", "", cleaned)
    if simplified in SKILL_ALIASES:
        return SKILL_ALIASES[simplified]

    return cleaned

import re, pathlib

readme = pathlib.Path("README.md").read_text(encoding="utf-8")

# Strip the "docs/" prefix from links, since this content will live
# inside the docs/ folder once copied to docs/index.md.
content = re.sub(r'(\]\()docs/', r'\1', readme)

# Add any front matter your Pages theme needs for its nav menu.
front_matter = "---\ntitle: Home\nnav_order: 1\n---\n\n"

pathlib.Path("docs/index.md").write_text(front_matter + content, encoding="utf-8")

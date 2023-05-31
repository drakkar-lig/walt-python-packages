# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import re
from pathlib import Path

import pypandoc
import sphinx_rtd_theme

THIS_DIR = Path(__file__).parent
print(THIS_DIR)

md_dir = THIS_DIR.parent / "md"


def need_rebuild(source, generated):
    if not generated.exists():
        return True
    if source.stat().st_mtime > generated.stat().st_mtime:
        return True
    return False


for md_file in tuple(md_dir.glob("*.md")):
    if md_file.name == "help-intro.md":
        rst_file = THIS_DIR / "index.rst"
    else:
        rst_file = (THIS_DIR / md_file.name).with_suffix(".rst")
    if need_rebuild(md_file, rst_file):
        print(f"Converting {md_file.name} to reStructuredText format.")
        # rst = reStructuredText; gfm = GitHub Flavored Markdown
        rst_content = pypandoc.convert_file(md_file, "rst", format="gfm")
        rst_content = re.sub(r"help-intro\.md", r"index.md", rst_content)
        rst_content = re.sub(
            r"```([a-z0-9 -]*)`` <([a-z0-9-]*)\.md>`__", r":doc:`\1 <\2>`", rst_content
        )
        if rst_file.name == "index.rst":
            index_rst_tables = (THIS_DIR / "index_rst_tables").read_text()
            rst_content = f"{rst_content}\n{index_rst_tables}"
        rst_file.write_text(rst_content)

static_dir = THIS_DIR / "_static"
static_dir.mkdir(exist_ok=True)


def get_version():
    code = compile((THIS_DIR / "version.py").read_text(), "<string>", "exec")
    local_env = {}
    eval(code, local_env)
    return local_env["__version__"]


project = "WalT"
copyright = "2012-2023, Members of the WALT project"
author = "Etienne Dublé"
release = get_version()

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]
html_static_path = ["_static"]
html_logo = "logo-walt.png"
html_theme_options = {
    "logo_only": False,
    "display_version": True,
    "style_nav_header_background": "gray",
    "sticky_navigation": False,
}
